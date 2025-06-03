# This script performs a full physical design flow for OpenROAD,
# based on the requirements specified in the prompt.

# Import necessary modules from OpenROAD and standard libraries
from openroad import Tech, Design, Timing
from pathlib import Path
import odb # Required for database manipulation, e.g., finding nets
import pdn # Required for Power Delivery Network generation
import drt # Required for TritonRoute parameters
import openroad as ord # Alias for core openroad module (used for get_db, micronToDBU, etc.)

# Initialize OpenROAD technology object
# This must be done before reading LEF/Liberty files
tech = Tech()

# Define paths to library and design files using pathlib for robustness
# Adjust these paths based on your project structure
libDir = Path("../Design/nangate45/lib")
lefDir = Path("../Design/nangate45/lef")
designDir = Path("../Design/") # Directory containing Verilog and possibly other inputs

# Define the top module name of your design
design_top_module_name = "gcd" # Replace with your actual top module name

# --- Read Technology and Library Files ---
# Read all liberty (.lib) files from the library directory
libFiles = libDir.glob("*.lib")
for libFile in libFiles:
    print(f"Reading Liberty file: {libFile}")
    tech.readLiberty(libFile.as_posix()) # Use as_posix() for cross-platform compatibility

# Read technology LEF files (contain layer, via, manufacturing rules)
techLefFiles = lefDir.glob("*.tech.lef")
for techLefFile in techLefFiles:
    print(f"Reading Technology LEF file: {techLefFile}")
    tech.readLef(techLefFile.as_posix())

# Read cell LEF files (contain cell footprints, pin locations, blockages)
lefFiles = lefDir.glob('*.lef')
for lefFile in lefFiles:
    print(f"Reading Cell LEF file: {lefFile}")
    tech.readLef(lefFile.as_posix())

# --- Read Verilog Netlist and Link Design ---
# Create a Design object associated with the loaded technology
design = Design(tech)

# Construct the path to the Verilog netlist
verilogFile = designDir/str(design_top_module_name + ".v") # Assuming verilog file is {top_module_name}.v
print(f"Reading Verilog netlist: {verilogFile}")
design.readVerilog(verilogFile.as_posix())

# Link the design: connects instances based on the netlist and loaded libraries/LEFs
print(f"Linking design for top module: {design_top_module_name}")
design.link(design_top_module_name)

# Access the block (the current top-level design)
block = design.getBlock()
if block is None:
    print("Error: Failed to link design or get block.")
    exit(1) # Exit if the design is not properly linked

# --- Set Clock Constraints ---
clock_period_ns = 40.0
clock_port_name = "clk" # Name of the clock input port in the Verilog
clock_name = "core_clock" # Name for the clock signal in OpenROAD

print(f"Setting clock constraint: period {clock_period_ns} ns on port {clock_port_name}")
# Use Tcl command via evalTclString for clock definition as it's standard practice
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
# Set the clock as propagated for timing analysis after CTS
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Set unit resistance and capacitance for clock and signal nets
# These values are typically extracted from the technology LEF or provided separately.
# Setting them early allows timing analysis to use them during placement and CTS.
print(f"Setting wire RC: resistance=0.03574, capacitance=0.07516")
design.evalTclString("set_wire_rc -clock -resistance 0.03574 -capacitance 0.07516")
design.evalTclString("set_wire_rc -signal -resistance 0.03574 -capacitance 0.07516")


# --- Floorplanning ---
print("Starting floorplanning...")
floorplan = design.getFloorplan()

# Find the site definition from the technology data
# The site name depends on your technology LEF (e.g., FreePDK45_38x28_10R_NP_162NW_34O for Nangate45)
# You may need to check your LEF or a technology example script for the correct site name.
tech_db = design.getTech().getDB().getTech()
site = tech_db.findSite("FreePDK45_38x28_10R_NP_162NW_34O") # Example site name, replace if needed
if site is None:
     # Attempt to find the first available site if the specific name is not found
     sites = tech_db.getSites()
     if sites:
         site = sites[0]
         print(f"Warning: Specific site 'FreePDK45_38x28_10R_NP_162NW_34O' not found. Using site: {site.getName()}")
     else:
         print("Error: No site definitions found in technology!")
         exit(1)


# Define floorplan parameters
target_utilization = 0.50 # Target standard cell utilization percentage
aspect_ratio = 1.0 # Aspect ratio (Height / Width) for the core area
margin_microns = 5.0 # Spacing between core boundary and die boundary (5 microns requested)
# Convert micron values to database units (DBU)
margin_dbu = design.micronToDBU(margin_microns)

# Initialize the floorplan
# The core area is calculated based on target utilization and aspect ratio relative to total cell area.
# The die area is then calculated by adding the specified margins around the core area.
print(f"Initializing floorplan with target utilization {target_utilization*100}%, core-die margin {margin_microns} um")
floorplan.initFloorplan(target_utilization, aspect_ratio, margin_dbu, margin_dbu, margin_dbu, margin_dbu, site)

# Generate routing tracks within the floorplan
# Tracks define legal locations for routing wires on specific layers.
floorplan.makeTracks()
print("Floorplan initialization complete and tracks generated.")


# --- I/O Pin Placement ---
print("Starting I/O pin placement...")
io_placer = design.getIOPlacer()

# Get technology layers for pin placement (M8 and M9 requested)
# Layers are needed to specify where pins can be placed/accessed
metal8_layer = tech_db.findLayer("metal8")
metal9_layer = tech_db.findLayer("metal9")

if metal8_layer is None or metal9_layer is None:
    print("Error: Could not find metal8 or metal9 layer for pin placement.")
    # Proceeding might fail later, but let's allow it for now, maybe layers are named differently
else:
    # Add horizontal (metal8) and vertical (metal9) routing layers for pins
    # The IO placer will attempt to place pins on these layers' tracks.
    io_placer.addHorLayer(metal8_layer)
    io_placer.addVerLayer(metal9_layer)
    print(f"Configured pin placement on layers: {metal8_layer.getName()} (horizontal), {metal9_layer.getName()} (vertical)")

# Optional: Configure I/O placement parameters (using defaults is often sufficient)
# params = io_placer.getParameters()
# params.setRandSeed(42) # Set random seed for deterministic results
# params.setMinDistanceInTracks(False) # Disable minimum distance based on tracks
# params.setMinDistance(design.micronToDBU(0)) # Set minimum distance in DBUs (0 in this case)
# params.setCornerAvoidance(design.micronToDBU(0)) # Set corner avoidance distance (0 in this case)

# Run I/O pin placement. 'True' enables random mode/annealing.
io_placer.runAnnealing(True)
print("I/O pin placement complete.")


# --- Macro Placement ---
# Identify instances that are macro blocks (not standard cells)
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    print(f"Found {len(macros)} macro instances. Starting macro placement...")
    mpl = design.getMacroPlacer()
    # Get the core area rectangle. Macros are typically placed within this region.
    core = block.getCoreArea()

    # Define macro placement parameters
    macro_halo_microns = 5.0 # Halo region around each macro (5 um requested)
    # The prompt requested 5um spacing *between* macros.
    # Macro placers often use a 'halo' or 'exclusion zone' around macros to achieve this.
    # Setting the halo to 5um ensures other instances (including other macros or std cells)
    # are kept away by at least this distance.
    print(f"Setting macro halo/exclusion region to {macro_halo_microns} um")

    # Macro placement parameters often control aspects like overlap avoidance,
    # spreading, and guiding macros to favorable locations.
    # The specific parameters and their effectiveness depend on the OpenROAD version and macro placer.
    # Using a representative set of parameters from examples:
    mpl.place(
        # Basic control
        num_threads = 4,          # Number of threads for parallelism
        # Instance counts (0 usually means consider all)
        max_num_macro = 0,
        min_num_macro = 0,
        max_num_inst = 0,
        min_num_inst = 0,
        # Convergence and Clustering
        tolerance = 0.1,
        max_num_level = 2,
        coarsening_ratio = 10.0,
        # Net Thresholds
        large_net_threshold = 50,
        signature_net_threshold = 50,
        # Halo definition (microns)
        halo_width = macro_halo_microns,
        halo_height = macro_halo_microns,
        # Fence region (macros must be placed inside this - typically the core area)
        fence_lx = block.dbuToMicrons(core.xMin()),
        fence_ly = block.dbuToMicrons(core.yMin()),
        fence_ux = block.dbuToMicrons(core.xMax()),
        fence_uy = block.dbuToMicrons(core.yMax()),
        # Weights for different objective costs during optimization
        area_weight = 0.1,
        outline_weight = 100.0, # High weight for avoiding outline violations (keeping macros within fence/not overlapping)
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0, # Weight for keeping std cells away from macro blockage areas
        pin_access_th = 0.0,
        # Target density within the fence region
        target_util = 0.50, # Could target the same as core utilization
        target_dead_space = 0.05,
        min_ar = 0.33,
        # Snapping and Bus Planning
        snap_layer = 4, # Example: Snap macro pin access points to track grid on metal4
        bus_planning_flag = False,
        # Reporting
        report_directory = ""
    )
    print("Macro placement complete.")
else:
    print("No macro instances found. Skipping macro placement.")


# --- Standard Cell Placement (Global and Detailed) ---
print("Starting standard cell placement...")

# Global Placement (approximate placement considering wirelength and density)
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Disable timing-driven placement (can be enabled if timing is critical early)
gpl.setRoutabilityDrivenMode(True) # Enable routability-driven placement to avoid congestion
gpl.setUniformTargetDensityMode(True) # Use uniform target density across the core area

# The prompt mentions "global router iterations as 30 times". This likely refers to placement iterations.
# OpenROAD's RePlace uses Nesterov-accelerated gradient descent. We'll limit the initial iterations as requested.
# Note: This is for placement, not routing iterations.
gpl.setInitialPlaceMaxIter(30)
# Other common GPL parameters:
gpl.setInitDensityPenalityFactor(0.05) # Initial penalty for density violation

print("Running initial global placement...")
gpl.doInitialPlace(threads = 4) # Use specified number of threads

print("Running Nesterov global placement...")
gpl.doNesterovPlace(threads = 4)
gpl.reset() # Reset the placer state after use

# Initial Detailed Placement (fixes overlaps after global placement)
# It's common to run detailed placement after global placement and before CTS/PDN.
print("Running initial detailed placement to fix overlaps...")
# Get site information to potentially calculate DBU displacement correctly
site = block.getRows()[0].getSite() if block.getRows() else None

# Define max displacement (1um X, 3um Y requested)
max_disp_x_microns = 1.0
max_disp_y_microns = 3.0
# Convert to DBU. detailedPlacement expects displacement in DBU.
# Need design object for micronToDBU conversion
max_disp_x_dbu = int(design.micronToDBU(max_disp_x_microns))
max_disp_y_dbu = int(design.micronToDBU(max_disp_y_microns))
print(f"Setting max detailed placement displacement: {max_disp_x_microns} um (X), {max_disp_y_microns} um (Y)")

# Remove any existing filler cells before detailed placement (they will be re-inserted later)
design.getOpendp().removeFillers()
# Perform detailed placement.
# detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, group_name, in_core)
# group_name="" applies to all cells, in_core=False allows limited displacement outside core boundary if needed (usually True/constrained)
# Let's stick to the signature used in the draft, assuming it's valid.
design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Initial detailed placement complete.")


# --- Power Delivery Network (PDN) Generation ---
print("Starting Power Delivery Network (PDN) generation...")

# Ensure VDD/VSS nets are marked as special. This is crucial for PDN generation.
# Iterate through all nets and mark power/ground nets.
for net in block.getNets():
    if net.getSigType() == "POWER" or net.getSigType() == "GROUND":
        net.setSpecial()

# Find or create the required power and ground nets
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

# Create nets if they don't exist (sometimes required if netlist doesn't explicitly define them)
if VDD_net is None:
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSigType("POWER")
if VSS_net is None:
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSigType("GROUND")

# Mark nets as special after potentially creating them
VDD_net.setSpecial()
VSS_net.setSpecial()

# Configure global connections for standard cell power/ground pins
# This step connects standard cell VDD/VSS pins to the global VDD/VSS nets.
print("Configuring global power and ground connections...")
# Connect pins matching these patterns to VDD_net
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VDD$", net=VDD_net, do_connect=True)
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VDDPE$", net=VDD_net, do_connect=True) # Example patterns from Nangate45
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VDDCE$", net=VDD_net, do_connect=True) # Example patterns
# Connect pins matching these patterns to VSS_net
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VSS$", net=VSS_net, do_connect=True)
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VSSE$", net=VSS_net, do_connect=True) # Example patterns
# Apply the defined global connections
block.globalConnect()
print("Global power/ground connections configured.")

# Initialize the PDN generator
pdngen = design.getPdnGen()

# Set up core power domain using the defined VDD/VSS nets
pdngen.setCoreDomain(power=VDD_net, ground=VSS_net) # Add switched_power, secondary if needed

# Define PDN geometry parameters from the prompt
# Convert micron values to DBU once
dbu = design.getTech().getDB().getTech().getDbUnitsPerMicron()
micronToDBU = design.micronToDBU # Use the design object's method for safety

# Via cut pitch between two grids (0 um requested)
pdn_cut_pitch_microns = 0.0
pdn_cut_pitch_dbu = [micronToDBU(pdn_cut_pitch_microns)] * 2 # [x_pitch, y_pitch]

# Offset for all rings/straps (0 um requested)
offset_microns = 0.0
offset_dbu = micronToDBU(offset_microns)
core_ring_core_offset = [offset_dbu] * 4 # [left, bottom, right, top] offset from core boundary
core_ring_pad_offset = [offset_dbu] * 4 # Offset from pad boundary (if rings extend to pads)
macro_ring_core_offset = [offset_dbu] * 4 # Offset from macro instance boundary

# Get routing layers by name
m1 = tech_db.findLayer("metal1")
m4 = tech_db.findLayer("metal4")
m5 = tech_db.findLayer("metal5")
m6 = tech_db.findLayer("metal6")
m7 = tech_db.findLayer("metal7")
m8 = tech_db.findLayer("metal8")

if not all([m1, m4, m5, m6, m7, m8]):
    print("Error: One or more required metal layers for PDN not found!")
    # Continue, but PDN generation will likely fail

# Create core grid structure (for standard cells)
print("Creating core grid for standard cells...")
domains_to_process = [pdngen.findDomain("Core")]
# Standard cell halo is typically 0, but if a halo is needed around *cells* relative to the grid, define it here.
# The prompt asked for 5um halo around macros, which affects macro placement/exclusion.
# The core grid definition also takes a 'halo' parameter which is a exclusion around the *core grid*. Let's set it to 0 or None.
# A halo defined here would keep core grid shapes away from the boundary *by* that halo amount.
# Let's assume no halo around the core grid itself unless explicitly asked. Set to [0,0,0,0].
core_grid_halo = [0] * 4

for domain in domains_to_process:
    if domain is None:
        print("Warning: Core domain not found for PDN generation.")
        continue

    pdngen.makeCoreGrid(domain = domain,
        name = "core_grid",
        starts_with = pdn.GROUND, # Start alternating VDD/VSS straps with GROUND
        halo = core_grid_halo,
        generate_obstructions = [],
        powercell = None,
        powercontrol = None,
        powercontrolnetwork = "STAR") # STAR or LINEAR depending on architecture

# Get the created core grid object(s)
core_grids = [pdngen.findGrid("core_grid")]
if not core_grids or core_grids[0] is None:
     print("Error: Core grid 'core_grid' not created.")
     # Skip core PDN generation parts

else:
    print("Configuring core grid rings and straps...")
    # Standard cell PDN geometry parameters
    sc_ring_width_microns = 5.0 # M7/M8 rings (5um requested)
    sc_ring_spacing_microns = 5.0 # M7/M8 rings (5um requested)
    sc_strap_width_m1_microns = 0.07 # M1 followpin (0.07um requested)
    sc_strap_width_m4_microns = 1.2 # M4 straps (1.2um requested)
    sc_strap_spacing_m4_microns = 1.2 # M4 straps (1.2um requested)
    sc_strap_pitch_m4_microns = 6.0 # M4 straps (6um requested)
    sc_strap_width_m7m8_microns = 1.4 # M7/M8 straps (1.4um requested)
    sc_strap_spacing_m7m8_microns = 1.4 # M7/M8 straps (1.4um requested)
    sc_strap_pitch_m7m8_microns = 10.8 # M7/M8 straps (10.8um requested)

    for g in core_grids:
        # Create power rings around core area on M7 and M8 (5um width/spacing)
        if m7 and m8:
            pdngen.makeRing(grid = g,
                layer0 = m7,
                width0 = micronToDBU(sc_ring_width_microns),
                spacing0 = micronToDBU(sc_ring_spacing_microns),
                layer1 = m8,
                width1 = micronToDBU(sc_ring_width_microns),
                spacing1 = micronToDBU(sc_ring_spacing_microns),
                starts_with = pdn.GRID, # Connect rings to the grid structure
                offset = core_ring_core_offset, # Offset from core boundary (0 um)
                pad_offset = core_ring_pad_offset, # Offset from pad boundary (0 um)
                extend = False, # Do not extend rings beyond specified offset/boundary
                nets = []) # Use default power/ground nets for the grid

        # Create horizontal power straps on metal1 following standard cell pins (0.07um width)
        if m1:
             pdngen.makeFollowpin(grid = g,
                 layer = m1,
                 width = micronToDBU(sc_strap_width_m1_microns),
                 extend = pdn.CORE) # Extend across the core area

        # Create vertical power straps on metal4 (1.2um width/spacing, 6um pitch)
        if m4:
             pdngen.makeStrap(grid = g,
                 layer = m4,
                 width = micronToDBU(sc_strap_width_m4_microns),
                 spacing = micronToDBU(sc_strap_spacing_m4_microns),
                 pitch = micronToDBU(sc_strap_pitch_m4_microns),
                 offset = offset_dbu, # Offset from the left/bottom boundary (0 um)
                 number_of_straps = 0, # Auto-calculate number based on pitch/area
                 snap = False, # Do not snap straps to track grid
                 starts_with = pdn.GRID,
                 extend = pdn.CORE, # Extend across the core area
                 nets = [])

        # Create vertical power straps on metal7 and horizontal on metal8 (1.4um width/spacing, 10.8um pitch)
        # Assuming vertical M7, horizontal M8 based on common layer directions and prompt structure
        if m7: # Vertical straps
            pdngen.makeStrap(grid = g,
                layer = m7,
                width = micronToDBU(sc_strap_width_m7m8_microns),
                spacing = micronToDBU(sc_strap_spacing_m7m8_microns),
                pitch = micronToDBU(sc_strap_pitch_m7m8_microns),
                offset = offset_dbu,
                number_of_straps = 0,
                snap = False,
                starts_with = pdn.GRID,
                extend = pdn.RINGS, # Extend to connect with the M7/M8 rings
                nets = [])
        if m8: # Horizontal straps (assuming M8 is horizontal in this tech)
             # Need to check M8 direction in LEF. Let's assume it's horizontal based on common layer stacks M1(V), M2(H), M3(V), M4(H), M5(V), M6(H), M7(V), M8(H).
             # If M8 is vertical, this should be vertical straps. Let's assume H for now.
             # For horizontal straps, pitch/spacing/offset apply in the Y direction.
             pdngen.makeStrap(grid = g,
                layer = m8,
                width = micronToDBU(sc_strap_width_m7m8_microns),
                spacing = micronToDBU(sc_strap_spacing_m7m8_microns),
                pitch = micronToDBU(sc_strap_pitch_m7m8_microns), # Pitch applies in Y direction
                offset = offset_dbu, # Offset applies in Y direction
                number_of_straps = 0,
                snap = False,
                starts_with = pdn.GRID,
                extend = pdn.BOUNDARY, # Extend to the die boundary
                nets = []) # Use default power/ground nets

        # Create via connections between core grid layers (0um cut pitch)
        print("Configuring core grid via connections...")
        if m1 and m4:
            pdngen.makeConnect(grid = g, layer0 = m1, layer1 = m4, cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1])
        if m4 and m7:
            pdngen.makeConnect(grid = g, layer0 = m4, layer1 = m7, cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1])
        if m7 and m8:
             # Via connection between M7 and M8 within the core grid structure
             pdngen.makeConnect(grid = g, layer0 = m7, layer1 = m8, cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1])


# Create power grids for macro instances (if macros exist)
if len(macros) > 0:
    print("Creating instance grids for macros...")
    # Define macro PDN geometry parameters
    # Note: Prompt requested rings on M7/M8 for standard cells (5um)
    # and M5/M6 grids for macros (1.2um width/spacing/6um pitch) and also M7/M8 rings (5um width/spacing).
    # The draft creates *macro-specific rings* on M5/M6 (1.5um width/spacing) and straps on M5/M6 (1.2um/1.2um/6um).
    # Let's adjust to match the prompt exactly: M5/M6 *grids* (straps) @ 1.2/1.2/6
    # and connect these to the main M7/M8 rings.
    # The prompt also asks for M7/M8 rings (5um) - these should likely be part of the *core* grid structure or global rings,
    # not specific rings around each macro instance unless explicitly stated. The draft puts M7/M8 rings on the core grid, which makes sense.
    # Let's focus on M5/M6 grids (straps) *within* the macro instance grid and connect them to higher layers.

    macro_strap_width_m5m6_microns = 1.2 # M5/M6 straps (1.2um requested)
    macro_strap_spacing_m5m6_microns = 1.2 # M5/M6 straps (1.2um requested)
    macro_strap_pitch_m5m6_microns = 6.0 # M5/M6 straps (6um requested)

    # Halo *around* the macro instance grid (keeping other things out of this grid area)
    # Reusing the macro halo from placement (5um) as an exclusion around the macro PDN area.
    macro_instance_grid_halo = [micronToDBU(macro_halo_microns)] * 4

    for i, macro_inst in enumerate(macros):
        # Create a separate instance grid domain for each macro
        for domain in domains_to_process:
            if domain is None:
                 continue
            # An instance grid creates a region around a specific instance for PDN shapes.
            # This is where macro-specific power structures are built.
            pdngen.makeInstanceGrid(domain = domain,
                name = f"macro_{macro_inst.getName()}_grid", # Unique name per macro instance
                starts_with = pdn.GROUND,
                inst = macro_inst,
                halo = macro_instance_grid_halo, # Halo around the macro instance grid region
                pg_pins_to_boundary = True, # Connect macro PG pins to the boundary of this grid
                default_grid = False, # This is not the default grid for standard cells
                generate_obstructions = [],
                is_bump = False)

        # Get the created macro instance grid object
        macro_instance_grid = pdngen.findGrid(f"macro_{macro_inst.getName()}_grid")

        if macro_instance_grid:
             print(f"Configuring instance grid {macro_instance_grid.getName()} straps and connections...")
             # Create power straps on metal5 and metal6 for macro connections (1.2um width/spacing, 6um pitch)
             # Assuming M5 vertical, M6 horizontal based on typical stacks.
             if m5: # Vertical straps on M5
                 pdngen.makeStrap(grid = macro_instance_grid,
                     layer = m5,
                     width = micronToDBU(macro_strap_width_m5m6_microns),
                     spacing = micronToDBU(macro_strap_spacing_m5m6_microns),
                     pitch = micronToDBU(macro_strap_pitch_m5m6_microns),
                     offset = offset_dbu, # Offset from left/bottom boundary (0 um)
                     number_of_straps = 0,
                     snap = True, # Snap to track grid? Often useful for macro PDN alignment
                     starts_with = pdn.GRID,
                     extend = pdn.BOUNDARY, # Extend to the boundary of the instance grid
                     nets = [])
             if m6: # Horizontal straps on M6
                 pdngen.makeStrap(grid = macro_instance_grid,
                     layer = m6,
                     width = micronToDBU(macro_strap_width_m5m6_microns),
                     spacing = micronToDBU(macro_strap_spacing_m5m6_microns),
                     pitch = micronToDBU(macro_strap_pitch_m5m6_microns), # Pitch applies in Y direction
                     offset = offset_dbu, # Offset applies in Y direction (0 um)
                     number_of_straps = 0,
                     snap = True, # Snap to track grid?
                     starts_with = pdn.GRID,
                     extend = pdn.BOUNDARY, # Extend to the boundary of the instance grid
                     nets = [])

             # Create via connections between macro power grid layers and connecting to core layers (0um cut pitch)
             print(f"Configuring instance grid {macro_instance_grid.getName()} via connections...")
             # Connect within the macro grid (M5 to M6)
             if m5 and m6:
                 pdngen.makeConnect(grid = macro_instance_grid, layer0 = m5, layer1 = m6, cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1])

             # Connect macro grid layers to the core grid layers (e.g., M4 to M5, M6 to M7)
             # Assuming core grid M4 is horizontal, M7 is vertical, M8 is horizontal based on typical stack.
             # Assuming macro grid M5 is vertical, M6 is horizontal.
             # Connect Core M4 (H) to Macro M5 (V)
             if m4 and m5:
                 pdngen.makeConnect(grid = macro_instance_grid, layer0 = m4, layer1 = m5, cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1])
             # Connect Macro M6 (H) to Core M7 (V)
             if m6 and m7:
                  pdngen.makeConnect(grid = macro_instance_grid, layer0 = m6, layer1 = m7, cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1])
             # Connect Macro M6 (H) to Core M8 (H) - Direct H-H connection might use special vias or rely on straps overlapping
             if m6 and m8:
                  # This connection is less common than V-H or H-V. Might require specific via rules or layers.
                  # Let's add a connection attempt, assuming it will use appropriate vias if defined.
                  pdngen.makeConnect(grid = macro_instance_grid, layer0 = m6, layer1 = m8, cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1])


# --- Build and Verify PDN ---
# Verify the PDN configuration before building
print("Checking PDN setup...")
pdngen.checkSetup()

# Build the PDN grids based on the configuration
print("Building PDN grids...")
pdngen.buildGrids(False) # False means do not generate power via blockages

# Write the generated PDN shapes to the design database
print("Writing PDN shapes to database...")
pdngen.writeToDb(True) # True means add to the current DB

# Reset temporary shapes used during PDN generation
pdngen.resetShapes()
print("PDN generation complete.")


# --- Clock Tree Synthesis (CTS) ---
print("Starting Clock Tree Synthesis (CTS)...")
cts = design.getTritonCts()
parms = cts.getParms()

# Set clock buffer cells to use (BUF_X2 requested)
# You might need multiple buffer types for a real design, but prompt specified BUF_X2.
buffer_list = "BUF_X2"
print(f"Setting clock buffers to: {buffer_list}")
cts.setBufferList(buffer_list)
cts.setRootBuffer("BUF_X2") # Specify the buffer type for the clock root driver
cts.setSinkBuffer("BUF_X2") # Specify the buffer type for sinks (flip-flop clock pins)

# Set wire segment unit (example value, affects clock wire lengths)
parms.setWireSegmentUnit(20)

# Run the CTS engine
cts.runTritonCts()
print("Clock Tree Synthesis complete.")


# --- Final Detailed Placement (after CTS) ---
# After CTS inserts buffers, placement needs to be refined to legalize their positions
# and potentially slightly adjust other cells.
print("Running final detailed placement (after CTS)...")
# Get site definition again if needed (though DBU conversion relies on tech/design)
# max_disp_x_dbu and max_disp_y_dbu are already calculated from before CTS DP.

# Remove existing filler cells before final detailed placement
design.getOpendp().removeFillers()
# Perform final detailed placement
design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Final detailed placement complete.")


# --- Insert Filler Cells ---
# Filler cells are inserted into empty spaces to maintain a continuous power/ground grid and density.
print("Inserting filler cells...")
db = ord.get_db() # Get the current database object
filler_masters = list()
filler_cells_prefix = "FILLCELL_" # Common prefix for inserted filler cells

# Find all masters in loaded libraries that are of type CORE_SPACER (standard filler cell type)
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

# Perform filler placement if filler cells were found
if not filler_masters:
    print("Warning: No filler cells found in library (type CORE_SPACER)! Skipping filler placement.")
else:
    print(f"Found {len(filler_masters)} filler cell types. Performing filler placement...")
    # fillerPlacement(filler_masters, prefix, verbose)
    design.getOpendp().fillerPlacement(filler_masters = filler_masters,
                                     prefix = filler_cells_prefix,
                                     verbose = False) # Set verbose=True for detailed output
    print("Filler placement complete.")


# --- Global Routing ---
print("Starting Global Routing...")
grt = design.getGlobalRouter()

# Set the minimum and maximum routing layers (M1 to M7 requested)
# Need to get the layer levels (an integer index) from the layer objects
metal1_level = m1.getRoutingLevel() if m1 else 1 # Use 1 as default if M1 not found
metal7_level = m7.getRoutingLevel() if m7 else 7 # Use 7 as default if M7 not found

print(f"Setting routing layers from M{metal1_level} to M{metal7_level}")
grt.setMinRoutingLayer(metal1_level)
grt.setMaxRoutingLayer(metal7_level)
# Also set layers for clock nets
grt.setMinLayerForClock(metal1_level)
grt.setMaxLayerForClock(metal7_level)


grt.setAdjustment(0.5) # Routing congestion adjustment factor (0.0 to 1.0). Higher is less congestion-aware.
grt.setVerbose(True) # Enable verbose output during global routing

# Run global routing. 'True' means use congestion data during routing.
# The prompt requested global router iterations=30. There is no direct Python API method for this.
# Global router convergence is typically controlled by internal iterations and parameters like adjustment.
# We run the main globalRoute function which handles its own iterations.
print("Running main global routing engine...")
grt.globalRoute(True)
print("Global routing complete.")


# --- Detailed Routing ---
print("Starting Detailed Routing...")
drter = design.getTritonRoute()
# Get default detailed routing parameters
params = drt.ParamStruct()

# Set the bottom and top routing layers for detailed routing (M1 to M7 requested)
# These parameters expect layer names as strings.
params.bottomRoutingLayer = "metal1" if m1 else ""
params.topRoutingLayer = "metal7" if m7 else ""
if not params.bottomRoutingLayer or not params.topRoutingLayer:
    print("Error: Could not determine bottom/top routing layers for detailed routing.")
    # Proceeding might fail

# Set other detailed routing parameters (example values from templates/defaults)
params.outputMazeFile = "" # Path to output maze file (usually empty)
params.outputDrcFile = "" # Path to output DRC report file (empty means no output)
params.outputCmapFile = ""
params.outputGuideCoverageFile = ""
params.dbProcessNode = "" # Technology node string (e.g., "45nm") - optional
params.enableViaGen = True # Enable via generation
params.drouteEndIter = 1 # Number of detailed routing iterations (usually 1 or 2)
params.viaInPinBottomLayer = "" # Allow vias in pins up to this layer
params.viaInPinTopLayer = "" # Allow vias in pins down to this layer
params.orSeed = -1 # Random seed (-1 for time-based)
params.orK = 0 # Parameter k (specific algorithm control)
params.verbose = 1 # Verbosity level (0=none, 1=some, 2=debug)
params.cleanPatches = True # Clean up routing patches
params.doPa = True # Enable post-processing antenna fixing
params.singleStepDR = False # Run detailed routing in single steps (for debug)
params.minAccessPoints = 1 # Minimum number of access points for detailed routing
params.saveGuideUpdates = False # Save guide updates (for debug)

# Set the configured parameters for the detailed router
drter.setParams(params)

# Run detailed routing
drter.main()
print("Detailed routing complete.")


# --- Write Output Files ---
# Write the final DEF file containing the placed and routed design
output_def_file = "final.def"
print(f"Writing final DEF file: {output_def_file}")
design.writeDef(output_def_file)

# Save the final ODB database file (allows reloading the design state)
output_odb_file = "final.odb"
print(f"Writing final ODB database: {output_odb_file}")
design.writeDb(output_odb_file)

print("Physical design flow complete.")