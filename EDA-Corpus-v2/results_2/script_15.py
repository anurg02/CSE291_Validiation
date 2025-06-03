import odb
import pdn
import drt
import openroad as ord
from openroad import Tech, Design, Timing, Replace, MacroPlacer, TritonCts, TritonRoute, GlobalRouter, IOPlacer
from pathlib import Path
import sys

# Initialize OpenROAD objects
# The Tech object is typically created automatically when using Design(tech) or reading technology data.
# We will use the design.getTech() method later to access technology information.

# Set paths to library and design files
# Assumes the script is run from a directory where ../Design/ exists
libDir = Path("../Design/nangate45/lib")
lefDir = Path("../Design/nangate45/lef")
designDir = Path("../Design/")

# --- USER: Specify Design Parameters ---
# Specify the top module name of the design
design_top_module_name = "your_top_module_name" # *** USER: Replace with your actual top module name ***
# Specify the path to your gate-level netlist file
verilogFile = designDir / "your_netlist.v" # *** USER: Replace with your actual netlist file path ***
# Specify the name of the clock port in the netlist
clock_port_name = "clk" # *** USER: Replace with your actual clock port name if different ***
# Specify the standard cell site name from your technology LEF
std_cell_site_name = "FreePDK45_38x28_10R_NP_162NW_34O" # *** USER: Replace with your actual standard cell site name ***
# Specify the names of power and ground nets in your netlist (or desired names)
power_net_name = "VDD" # *** USER: Replace with your actual VDD net name if different ***
ground_net_name = "VSS" # *** USER: Replace with your actual VSS net name if different ***
# Specify the name of the clock buffer cell to use for CTS
clock_buffer_cell = "BUF_X2" # *** USER: Replace with your actual buffer cell name if different ***
# Specify the prefix for filler cells in your library
filler_cells_prefix = "FILLCELL_" # *** USER: Adjust prefix if your fillers have a different name ***
# Specify metal layer names used in the technology LEF
metal1_name = "metal1"
metal4_name = "metal4"
metal5_name = "metal5"
metal6_name = "metal6"
metal7_name = "metal7"
metal8_name = "metal8"
metal9_name = "metal9"
# --- End User Parameters ---


# --- Read Design and Libraries ---
print("--- Reading Design and Libraries ---")
# Load liberty timing libraries
libFiles = list(libDir.glob("*.lib"))
if not libFiles:
    print(f"Error: No .lib files found in {libDir}", file=sys.stderr)
    sys.exit(1)

# Load technology and cell LEF files
techLefFiles = list(lefDir.glob("*.tech.lef"))
lefFiles = list(lefDir.glob('*.lef'))
if not techLefFiles and not lefFiles:
     print(f"Error: No .lef files found in {lefDir}", file=sys.stderr)
     sys.exit(1)

# Create a temporary Tech object to read files, then use it to create Design
# The Design constructor reads tech LEFs implicitly if available.
temp_tech = Tech()
for libFile in libFiles:
    print(f"Reading liberty: {libFile}")
    temp_tech.readLiberty(libFile.as_posix())
for techLefFile in techLefFiles:
    print(f"Reading tech LEF: {techLefFile}")
    temp_tech.readLef(techLefFile.as_posix())
for lefFile in lefFiles:
    print(f"Reading LEF: {lefFile}")
    temp_tech.readLef(lefFile.as_posix())

# Create design and read Verilog netlist
design = Design(temp_tech) # Associate design with the tech data just read
print(f"Reading Verilog: {verilogFile}")
design.readVerilog(verilogFile.as_posix())

print(f"Linking design: {design_top_module_name}")
success = design.link(design_top_module_name)
if not success:
    print(f"Error: Could not link design {design_top_module_name}", file=sys.stderr)
    sys.exit(1)
print("Design successfully linked.")

# Get the DB object from the design for accessing database elements
db = design.getTech().getDB()
tech = db.getTech()

# --- Configure Clock Constraints ---
print("--- Configuring Clock Constraints ---")
clock_period_ns = 50
clock_name = "core_clock"
# Check if clock port exists
clock_port = design.getBlock().findBTerm(clock_port_name)
if not clock_port:
    print(f"Warning: Clock port '{clock_port_name}' not found in design.", file=sys.stderr)
    # Proceeding without clock definition, may fail later stages

# Create clock signal with 50ns period on 'clk' port and name it 'core_clock'
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
print(f"Created clock '{clock_name}' on port '{clock_port_name}' with period {clock_period_ns} ns.")
# Propagate the clock signal
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")
print(f"Set '{clock_name}' as propagated clock.")

# --- Floorplanning ---
print("--- Performing Floorplanning ---")
floorplan = design.getFloorplan()
# Set target utilization to 35% and aspect ratio to 1.0
utilization = 0.35
aspect_ratio = 1.0
# Set spacing between core and die area to 12um on all sides
margin_um = 12
margin_dbu = design.micronToDBU(margin_um)
bottomSpace = margin_dbu
topSpace = margin_dbu
leftSpace = margin_dbu
rightSpace = margin_dbu

# Find the standard cell site from the technology LEF
site = floorplan.findSite(std_cell_site_name)
if site is None:
    print(f"Error: Standard cell site '{std_cell_site_name}' not found in technology LEF.", file=sys.stderr)
    sys.exit(1)
print(f"Found standard cell site: {site.getName()}")

# Initialize the floorplan with the specified parameters
print(f"Initializing floorplan with utilization={utilization}, margin={margin_um} um")
floorplan.initFloorplan(utilization, aspect_ratio, bottomSpace, topSpace, leftSpace, rightSpace, site)
# Create placement rows based on the site definition
print("Creating placement rows.")
floorplan.makeTracks()
print("Floorplanning complete.")

# Write DEF file after floorplanning
print("Writing floorplan.def")
design.writeDef("floorplan.def")

# --- I/O Pin Placement ---
print("--- Performing I/O Pin Placement ---")
io_placer = design.getIOPlacer()
io_params = io_placer.getParameters()
# Set random seed for reproducibility
io_params.setRandSeed(42)
# Do not enforce minimum distance in tracks, use specified distance (0 in this case)
io_params.setMinDistanceInTracks(False)
# Set minimum distance between pins to 0um (no minimum requested)
io_params.setMinDistance(design.micronToDBU(0))
# Set corner avoidance distance to 0um (allow pins near corners requested implicitly by no constraint)
io_params.setCornerAvoidance(design.micronToDBU(0))

# Place I/O pins on metal8 (horizontal) and metal9 (vertical) layers
metal8 = tech.findLayer(metal8_name)
metal9 = tech.findLayer(metal9_name)

layers_added = 0
if metal8:
    print(f"Adding {metal8_name} for horizontal IO placement.")
    io_placer.addHorLayer(metal8)
    layers_added += 1
else:
    print(f"Warning: Metal layer '{metal8_name}' not found for IO placement.", file=sys.stderr)
if metal9:
    print(f"Adding {metal9_name} for vertical IO placement.")
    io_placer.addVerLayer(metal9)
    layers_added += 1
else:
     print(f"Warning: Metal layer '{metal9_name}' not found for IO placement.", file=sys.stderr)

if layers_added == 0:
    print("Error: No valid metal layers specified for IO placement.", file=sys.stderr)
    # Proceeding, but IO placement will likely fail or be ineffective

# Run IO placement using annealing algorithm (random mode enabled as in draft)
IOPlacer_random_mode = True
print("Running IO placement.")
io_placer.runAnnealing(IOPlacer_random_mode)
print("I/O Pin Placement complete.")

# Write DEF file after IO placement
print("Writing io_placement.def")
design.writeDef("io_placement.def")

# --- Macro Placement ---
print("--- Performing Macro Placement ---")
# Find all instances that are macros (have masters of type BLOCK or PAD/AREA_BUMP based on typical definitions)
# A common check is master.isBlock()
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    print(f"Found {len(macros)} macros. Running macro placement.")
    mpl = design.getMacroPlacer()
    block = design.getBlock()
    # Use the core area as the fence region for macros as in draft and common practice
    core = block.getCoreArea()
    # Set halo region around each macro as requested (5um)
    halo_um = 5.0
    # The MacroPlacer API uses microns for halo width/height directly
    # The API does not have a direct parameter for minimum spacing BETWEEN macros.
    # The halo helps maintain separation and routing/placement keepouts.

    # Align macro pins on Metal 4 to the track grid (as in draft/examples)
    snap_layer = tech.findLayer(metal4_name)
    snap_layer_level = snap_layer.getRoutingLevel() if snap_layer else 0 # Default to 0 if layer not found
    if not snap_layer:
        print(f"Warning: Metal layer '{metal4_name}' not found for macro pin snapping.", file=sys.stderr)

    print(f"Placing {len(macros)} macros...")
    # Macro placer parameters (using defaults from examples where not specified in prompt)
    mpl.place(
        num_threads = 64,
        max_num_macro = len(macros), # Place all macros found
        min_num_macro = 0,
        max_num_inst = 0, # Do not place standard cells with macro placer
        min_num_inst = 0,
        tolerance = 0.1,
        max_num_level = 2,
        coarsening_ratio = 10.0,
        large_net_threshold = 50,
        signature_net_threshold = 50,
        halo_width = halo_um,
        halo_height = halo_um,
        # Fence region is the core area
        fence_lx = block.dbuToMicrons(core.xMin()),
        fence_ly = block.dbuToMicrons(core.yMin()),
        fence_ux = block.dbuToMicrons(core.xMax()),
        fence_uy = block.dbuToMicrons(core.yMax()),
        area_weight = 0.1,
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        pin_access_th = 0.0,
        target_util = 0.25, # This is a target utilization within the macro placer's algorithm area partitioning
        target_dead_space = 0.05,
        min_ar = 0.33,
        snap_layer = snap_layer_level, # Snap pins on this layer to track grid
        bus_planning_flag = False,
        report_directory = "" # Empty string means no report directory
    )
    print("Macro Placement complete.")
else:
    print("No macros found. Skipping macro placement.")

# --- Standard Cell Placement (Global and Detailed) ---
print("--- Performing Standard Cell Placement ---")
# Get global placer object
gpl = design.getReplace()

# Disable timing-driven mode, enable routability-driven mode as in draft
gpl.setTimingDrivenMode(False)
gpl.setRoutabilityDrivenMode(True)
# Enable uniform target density mode
gpl.setUniformTargetDensityMode(True)

# The prompt requested "Set the iteration of the global router as 20 times".
# Global Routing (TritonGR) does not have a simple top-level 'iteration' parameter.
# Triton-Replace's 'InitialPlaceMaxIter' affects the initial random placement, not global routing.
# Removing the 'setInitialPlaceMaxIter' call as it doesn't apply to global routing iterations.
print("Running initial global placement.")
gpl.doInitialPlace(threads = 4)
print("Running Nesterov global placement.")
gpl.doNesterovPlace(threads = 4)
# Reset placer state (optional, but good practice)
gpl.reset()
print("Global Placement complete.")

# Run initial detailed placement to legalize cells after global placement
print("Running initial detailed placement.")
# Get the site definition from the first row (assuming rows were made)
rows = design.getBlock().getRows()
if not rows:
    print("Error: No placement rows found.", file=sys.stderr)
    # Proceeding, but detailed placement may fail
    site = None
else:
    site = rows[0].getSite()
    if not site:
         print("Error: Could not get site from placement row.", file=sys.stderr)
         # Proceeding, but detailed placement may fail

# Set maximum displacement allowed during detailed placement
max_disp_x_um = 0.5
max_disp_y_um = 0.5
max_disp_x = int(design.micronToDBU(max_disp_x_um))
max_disp_y = int(design.micronToDBU(max_disp_y_um))
print(f"Setting detailed placement max displacement to X={max_disp_x_um} um, Y={max_disp_y_um} um.")

opendp = design.getOpendp()
# Before detailed placement, remove any existing filler cells if they were previously inserted
# (unlikely at this stage unless running incremental flow, but safe to call)
opendp.removeFillers()
# Perform detailed placement with specified max displacement
if site: # Only run if we have a valid site
    opendp.detailedPlacement(max_disp_x, max_disp_y, site.getName(), False) # Pass site name

print("Detailed Placement complete.")

# Write DEF file after placement (macro, global, and detailed)
print("Writing placement.def")
design.writeDef("placement.def")

# --- Power Delivery Network (PDN) Generation ---
print("--- Generating Power Delivery Network (PDN) ---")
pdngen = design.getPdnGen()

# Set up global power/ground connections
# Mark power and ground nets as special nets so they are handled correctly by the router
print(f"Marking nets '{power_net_name}' and '{ground_net_name}' as special.")
# Find existing power and ground nets or create them if needed
VDD_net = design.getBlock().findNet(power_net_name)
VSS_net = design.getBlock().findNet(ground_net_name)
switched_power = None # No switched power domain specified
secondary = list() # No secondary power nets specified

# Create VDD/VSS nets if they don't exist in the netlist
if VDD_net == None:
    print(f"Net '{power_net_name}' not found. Creating special power net.")
    VDD_net = odb.dbNet_create(design.getBlock(), power_net_name)
    VDD_net.setSpecial()
    VDD_net.setSigType("POWER")
else:
     VDD_net.setSpecial()
     VDD_net.setSigType("POWER") # Ensure it's marked as POWER

if VSS_net == None:
    print(f"Net '{ground_net_name}' not found. Creating special ground net.")
    VSS_net = odb.dbNet_create(design.getBlock(), ground_net_name)
    VSS_net.setSpecial()
    VSS_net.setSigType("GROUND")
else:
    VSS_net.setSpecial()
    VSS_net.setSigType("GROUND") # Ensure it's marked as GROUND

# Connect power pins of standard cells to global power/ground nets
# This connects common standard cell power/ground pin names to the global nets
print(f"Adding global connections for {power_net_name} and {ground_net_name}.")
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDPE$", net = VDD_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDCE$", net = VDD_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSSE$", net = VSS_net, do_connect = True)
# Apply the global connections
design.getBlock().globalConnect()
print("Global connections applied.")

# Configure power domains
# Set core power domain with primary power/ground nets
print(f"Setting core power domain with power net '{power_net_name}' and ground net '{ground_net_name}'.")
pdngen.setCoreDomain(power = VDD_net, switched_power = switched_power, ground = VSS_net, secondary = secondary)
domains = [pdngen.findDomain("Core")]
if not domains[0]:
     print("Error: Core domain not found after setting. Cannot proceed with PDN grid setup.", file=sys.stderr)
     sys.exit(1)

# Set via cut pitch to 0 μm for connections between grids as requested
pdn_cut_pitch_um = 0
pdn_cut_pitch_dbu = design.micronToDBU(pdn_cut_pitch_um)
pdn_cut_pitch = [pdn_cut_pitch_dbu, pdn_cut_pitch_dbu]
print(f"Setting PDN via cut pitch between grids to {pdn_cut_pitch_um} um.")

# Get metal layers for power grid implementation
m1 = tech.findLayer(metal1_name)
m4 = tech.findLayer(metal4_name)
m5 = tech.findLayer(metal5_name)
m6 = tech.findLayer(metal6_name)
m7 = tech.findLayer(metal7_name)
m8 = tech.findLayer(metal8_name)

metal_layers_found = {
    metal1_name: m1, metal4_name: m4, metal5_name: m5,
    metal6_name: m6, metal7_name: m7, metal8_name: m8
}

# Create power grid for standard cells (Core domain)
print("Creating core power grid.")
core_grid_name = "core_grid"
# The Core grid typically covers the entire core area
pdngen.makeCoreGrid(domain = domains[0],
    name = core_grid_name,
    starts_with = pdn.GROUND, # Start with ground net straps/rings
    pin_layers = [], # Optional: specify layers for connecting to cell pins
    generate_obstructions = [], # Optional: specify layers to generate routing obstructions
    powercell = None, # Optional: power cell instance
    powercontrol = None, # Optional: power control net
    powercontrolnetwork = "STAR") # Optional: power control network type

# Get the created core grid object
core_grid = pdngen.findGrid(core_grid_name)
if not core_grid:
     print(f"Error: Core grid '{core_grid_name}' not found after creation attempt.", file=sys.stderr)
     # Proceeding, but PDN straps/rings will not be added

if core_grid:
    # The makeCoreGrid/makeInstanceGrid calls return a list of objects,
    # even if only one grid is created. Iterate through them.
    for g in core_grid:
        print(f"Configuring patterns for core grid '{g.getName()}'.")
        # Add patterns to the core grid
        # Create horizontal power straps on metal1 following standard cell power rails
        m1_width_um = 0.07
        if metal_layers_found.get(metal1_name):
            print(f"Adding {metal1_name} followpins (width={m1_width_um} um) to core grid.")
            pdngen.makeFollowpin(grid = g,
                layer = m1,
                width = design.micronToDBU(m1_width_um),
                extend = pdn.CORE)
        else:
            print(f"Warning: Metal layer '{metal1_name}' not found for core grid followpins.", file=sys.stderr)

        # Create power straps on metal4
        m4_width_um = 1.2
        m4_spacing_um = 1.2
        m4_pitch_um = 6
        m4_offset_um = 0
        if metal_layers_found.get(metal4_name):
            print(f"Adding {metal4_name} straps (width={m4_width_um}, spacing={m4_spacing_um}, pitch={m4_pitch_um} um) to core grid.")
            pdngen.makeStrap(grid = g,
                layer = m4,
                width = design.micronToDBU(m4_width_um),
                spacing = design.micronToDBU(m4_spacing_um),
                pitch = design.micronToDBU(m4_pitch_um),
                offset = design.micronToDBU(m4_offset_um),
                number_of_straps = 0, # Auto-calculate number of straps
                snap = False, # Usually snap to grid for straps is True, but draft had False
                starts_with = pdn.GRID, # Start based on grid definition (GROUND)
                extend = pdn.CORE, # Extend within the core area
                nets = []) # Apply to all nets in the domain (VDD/VSS)
        else:
            print(f"Warning: Metal layer '{metal4_name}' not found for core grid straps.", file=sys.stderr)


        # Create power straps on metal7
        m7_width_um = 1.4
        m7_spacing_um = 1.4
        m7_pitch_um = 10.8
        m7_offset_um = 0
        if metal_layers_found.get(metal7_name):
            print(f"Adding {metal7_name} straps (width={m7_width_um}, spacing={m7_spacing_um}, pitch={m7_pitch_um} um) to core grid.")
            pdngen.makeStrap(grid = g,
                layer = m7,
                width = design.micronToDBU(m7_width_um),
                spacing = design.micronToDBU(m7_spacing_um),
                pitch = design.micronToDBU(m7_pitch_um),
                offset = design.micronToDBU(m7_offset_um),
                number_of_straps = 0,
                snap = False,
                starts_with = pdn.GRID,
                extend = pdn.CORE,
                nets = [])
        else:
            print(f"Warning: Metal layer '{metal7_name}' not found for core grid straps.", file=sys.stderr)


        # Create power straps on metal8 (extend to boundary as in examples)
        # Note: This might overlap with rings on M8. Check PDN spec.
        # The prompt asked for M8 rings, and M7/M8 grid straps.
        # A common setup is horizontal straps on one layer (e.g. M7), vertical on another (e.g. M8), and rings on outer layers (e.g. M7/M8).
        # Following the prompt explicitly, adding both M7/M8 straps and M7/M8 rings.
        m8_width_um = 1.4
        m8_spacing_um = 1.4
        m8_pitch_um = 10.8
        m8_offset_um = 0
        if metal_layers_found.get(metal8_name):
            print(f"Adding {metal8_name} straps (width={m8_width_um}, spacing={m8_spacing_um}, pitch={m8_pitch_um} um) to core grid.")
            pdngen.makeStrap(grid = g,
                layer = m8,
                width = design.micronToDBU(m8_width_um),
                spacing = design.micronToDBU(m8_spacing_um),
                pitch = design.micronToDBU(m8_pitch_um),
                offset = design.micronToDBU(m8_offset_um),
                number_of_straps = 0,
                snap = False,
                starts_with = pdn.GRID,
                extend = pdn.BOUNDARY, # Extend to chip boundary
                nets = [])
        else:
            print(f"Warning: Metal layer '{metal8_name}' not found for core grid straps.", file=sys.stderr)

        # Create power rings on metal7 and metal8 around the core area
        m7_ring_width_um = 4
        m7_ring_spacing_um = 4
        m8_ring_width_um = 4
        m8_ring_spacing_um = 4
        ring_offset_um = [0, 0, 0, 0] # Offset 0um as requested
        pad_offset_um = [0, 0, 0, 0] # Pad offset 0um as requested for unspecified parameters
        macro_ring_connect_to_pad_layers = list() # Not connecting rings to pads here

        if metal_layers_found.get(metal7_name) and metal_layers_found.get(metal8_name):
             print(f"Adding rings on {metal7_name} (width={m7_ring_width_um}, spacing={m7_ring_spacing_um} um) and {metal8_name} (width={m8_ring_width_um}, spacing={m8_ring_spacing_um} um) around core.")
             pdngen.makeRing(grid = g,
                layer0 = m7,
                width0 = design.micronToDBU(m7_ring_width_um),
                spacing0 = design.micronToDBU(m7_ring_spacing_um),
                layer1 = m8,
                width1 = design.micronToDBU(m8_ring_width_um),
                spacing1 = design.micronToDBU(m8_ring_spacing_um),
                starts_with = pdn.GRID, # Start based on grid definition (GROUND)
                offset = [design.micronToDBU(o) for o in ring_offset_um], # Offset 0um
                pad_offset = [design.micronToDBU(o) for o in pad_offset_um], # Pad offset 0um
                extend = False, # Ring stays around the core area defined by initFloorplan
                pad_pin_layers = macro_ring_connect_to_pad_layers,
                nets = []) # Apply to all nets in the domain (VDD/VSS)
        else:
            print(f"Warning: Metal layers '{metal7_name}' or '{metal8_name}' not found for core grid rings.", file=sys.stderr)


        # Create via connections between standard cell grid layers
        print("Adding via connections between core grid layers.")
        # Connect metal1 to metal4
        if metal_layers_found.get(metal1_name) and metal_layers_found.get(metal4_name):
            pdngen.makeConnect(grid = g, layer0 = m1, layer1 = m4, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1]) # Other params default
            print(f"Connected {metal1_name} to {metal4_name}.")
        else:
             print(f"Warning: Cannot connect {metal1_name} to {metal4_name}, one or both layers not found.")

        # Connect metal4 to metal7
        if metal_layers_found.get(metal4_name) and metal_layers_found.get(metal7_name):
            pdngen.makeConnect(grid = g, layer0 = m4, layer1 = m7, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
            print(f"Connected {metal4_name} to {metal7_name}.")
        else:
             print(f"Warning: Cannot connect {metal4_name} to {metal7_name}, one or both layers not found.")

        # Connect metal7 to metal8
        if metal_layers_found.get(metal7_name) and metal_layers_found.get(metal8_name):
            pdngen.makeConnect(grid = g, layer0 = m7, layer1 = m8, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
            print(f"Connected {metal7_name} to {metal8_name}.")
        else:
             print(f"Warning: Cannot connect {metal7_name} to {metal8_name}, one or both layers not found.")


# Create power grid for macro blocks if macros exist
if len(macros) > 0:
    print("Configuring PDN for macros.")
    # Set halo around macros for macro instance grid routing using the 5um halo value
    macro_grid_halo_um = halo_um
    macro_grid_halo = [design.micronToDBU(macro_grid_halo_um) for i in range(4)]
    print(f"Setting macro grid halo to {macro_grid_halo_um} um.")

    for i in range(len(macros)):
        macro_instance = macros[i]
        print(f"Creating instance grid for macro: {macro_instance.getName()}")
        # Create separate power grid for each macro instance
        # PDN generator adds this grid to the domain automatically
        macro_grid_name = f"CORE_macro_grid_{i}"
        pdngen.makeInstanceGrid(domain = domains[0], # Associate with the core domain
            name = macro_grid_name,
            starts_with = pdn.GROUND, # Start with ground net
            inst = macro_instance, # Associate with this specific macro instance
            halo = macro_grid_halo, # Add halo around the instance boundary
            pg_pins_to_boundary = True, # Connect macro power/ground pins to the grid boundary
            default_grid = False, # This is a specific instance grid, not the default core grid
            generate_obstructions = [], # Optional
            is_bump = False) # Optional

        # Get the created macro instance grid object(s)
        # makeInstanceGrid returns a list
        macro_grids = pdngen.findGrid(macro_grid_name)

        if macro_grids:
            for g in macro_grids:
                print(f"Configuring patterns for macro instance grid '{g.getName()}'.")
                # Add strap patterns to the macro grid
                # Create power straps on metal5 for macro connections
                m5_width_um = 1.2
                m5_spacing_um = 1.2
                m5_pitch_um = 6
                m5_offset_um = 0
                if metal_layers_found.get(metal5_name):
                    print(f"Adding {metal5_name} straps (width={m5_width_um}, spacing={m5_spacing_um}, pitch={m5_pitch_um} um) to macro grid.")
                    pdngen.makeStrap(grid = g,
                        layer = m5,
                        width = design.micronToDBU(m5_width_um),
                        spacing = design.micronToDBU(m5_spacing_um),
                        pitch = design.micronToDBU(m5_pitch_um),
                        offset = design.micronToDBU(m5_offset_um),
                        number_of_straps = 0,
                        snap = True, # Snap to grid is typically desired for instance grids
                        starts_with = pdn.GRID,
                        extend = pdn.CORE, # Extend within the macro instance boundary defined by halo
                        nets = [])
                else:
                     print(f"Warning: Metal layer '{metal5_name}' not found for macro grid straps.", file=sys.stderr)

                # Create power straps on metal6 for macro connections
                m6_width_um = 1.2
                m6_spacing_um = 1.2
                m6_pitch_um = 6
                m6_offset_um = 0
                if metal_layers_found.get(metal6_name):
                    print(f"Adding {metal6_name} straps (width={m6_width_um}, spacing={m6_spacing_um}, pitch={m6_pitch_um} um) to macro grid.")
                    pdngen.makeStrap(grid = g,
                        layer = m6,
                        width = design.micronToDBU(m6_width_um),
                        spacing = design.micronToDBU(m6_spacing_um),
                        pitch = design.micronToDBU(m6_pitch_um),
                        offset = design.micronToDBU(m6_offset_um),
                        number_of_straps = 0,
                        snap = True,
                        starts_with = pdn.GRID,
                        extend = pdn.CORE, # Extend within the macro instance boundary defined by halo
                        nets = [])
                else:
                    print(f"Warning: Metal layer '{metal6_name}' not found for macro grid straps.", file=sys.stderr)

                # Create via connections between macro power grid layers
                # Connect metal4 (from core grid) to metal5 (macro grid) - assumes M4 connects to macro pins
                # Assumes M4 is available within the macro halo area
                if metal_layers_found.get(metal4_name) and metal_layers_found.get(metal5_name):
                    pdngen.makeConnect(grid = g, layer0 = m4, layer1 = m5, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
                    print(f"Connected {metal4_name} to {metal5_name} for macro grid.")
                else:
                    print(f"Warning: Cannot connect {metal4_name} to {metal5_name} for macro grid, one or both layers not found.")

                # Connect metal5 to metal6 (macro grid layers)
                if metal_layers_found.get(metal5_name) and metal_layers_found.get(metal6_name):
                    pdngen.makeConnect(grid = g, layer0 = m5, layer1 = m6, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
                    print(f"Connected {metal5_name} to {metal6_name} for macro grid.")
                else:
                    print(f"Warning: Cannot connect {metal5_name} to {metal6_name} for macro grid, one or both layers not found.")

                # Connect metal6 (macro grid) to metal7 (core grid) - assumes M7 connects to macro pins
                # Assumes M7 is available within the macro halo area
                if metal_layers_found.get(metal6_name) and metal_layers_found.get(metal7_name):
                    pdngen.makeConnect(grid = g, layer0 = m6, layer1 = m7, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
                    print(f"Connected {metal6_name} to {metal7_name} for macro grid.")
                else:
                     print(f"Warning: Cannot connect {metal6_name} to {metal7_name} for macro grid, one or both layers not found.")

        else:
             print(f"Warning: Instance grid '{macro_grid_name}' not found after creation attempt for macro {macro_instance.getName()}.", file=sys.stderr)


# Generate the final power delivery network shapes
print("Checking PDN setup.")
pdngen.checkSetup() # Verify PDN configuration
print("Building PDN grids (shapes).")
pdngen.buildGrids(False) # Build the power grid shapes in memory (False means don't generate PG pins yet)
print("Writing PDN shapes to the design database.")
pdngen.writeToDb(True, ) # Write power grid shapes to the design database (True means also generate PG pins for std cells)
pdngen.resetShapes() # Reset temporary shapes used during build
print("PDN Generation complete.")

# Write DEF file after PDN generation
print("Writing pdn.def")
design.writeDef("pdn.def")

# --- Clock Tree Synthesis (CTS) ---
print("--- Performing Clock Tree Synthesis (CTS) ---")
# Set unit resistance and capacitance for clock nets as requested
clock_wire_r = 0.03574
clock_wire_c = 0.07516
signal_wire_r = 0.03574
signal_wire_c = 0.07516

design.evalTclString(f"set_wire_rc -clock -resistance {clock_wire_r} -capacitance {clock_wire_c}")
print(f"Set clock wire RC: R={clock_wire_r}, C={clock_wire_c}")
# Set unit resistance and capacitance for signal nets as requested
design.evalTclString(f"set_wire_rc -signal -resistance {signal_wire_r} -capacitance {signal_wire_c}")
print(f"Set signal wire RC: R={signal_wire_r}, C={signal_wire_c}")

# Get TritonCTS object
cts = design.getTritonCts()
# Get CTS parameters (optional, often defaults are fine)
cts_parms = cts.getParms()
# Set wire segment unit (adjust as needed for target technology)
cts_parms.setWireSegmentUnit(20) # Example value

# Specify the clock buffer cell list
# Check if the buffer cell exists
buffer_master = design.getBlock().findMaster(clock_buffer_cell)
if not buffer_master:
    print(f"Error: Clock buffer cell '{clock_buffer_cell}' not found in library. Cannot perform CTS.", file=sys.stderr)
    # Proceeding, but CTS will fail
else:
    print(f"Using clock buffer cell: {clock_buffer_cell}")
    cts.setBufferList(clock_buffer_cell) # Can be a space-separated string list
    # Specify the root clock buffer cell (optional, often same as buffer list)
    cts.setRootBuffer(clock_buffer_cell)
    # Specify the sink clock buffer cell (optional)
    cts.setSinkBuffer(clock_buffer_cell)

    # Run CTS
    print("Running TritonCTS.")
    cts.runTritonCts()
    print("Clock Tree Synthesis complete.")

# Write DEF file after CTS
print("Writing cts.def")
design.writeDef("cts.def")

# --- Detailed Placement (Post-CTS) ---
# Need to run detailed placement again after CTS might have moved cells or inserted buffers
print("--- Performing Post-CTS Detailed Placement ---")
# Use the same max displacement constraints as before
if site: # Only run if we have a valid site from floorplanning
    print(f"Running post-CTS detailed placement with max displacement X={max_disp_x_um} um, Y={max_disp_y_um} um.")
    opendp.detailedPlacement(max_disp_x, max_disp_y, site.getName(), False) # Pass site name
    print("Post-CTS Detailed Placement complete.")
else:
    print("Skipping post-CTS detailed placement due to missing site information.")


# --- Filler Cell Insertion ---
print("--- Inserting Filler Cells ---")
# Find CORE_SPACER type masters (filler cells) in the libraries
db = design.getTech().getDB()
filler_masters = list()
found_filler_prefix = False
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
             # Optional: filter by prefix if needed, but type is usually sufficient
             # if master.getName().startswith(filler_cells_prefix):
             filler_masters.append(master)
             if master.getName().startswith(filler_cells_prefix):
                 found_filler_prefix = True

if not filler_masters:
    print("Warning: No filler cells (CORE_SPACER type masters) found in library! Cannot perform filler placement.", file=sys.stderr)
elif not found_filler_prefix:
     print(f"Warning: No filler cells found starting with prefix '{filler_cells_prefix}'. Check if this prefix is correct for your library.", file=sys.stderr)

# Perform filler cell placement if filler masters were found
if filler_masters:
    print(f"Found {len(filler_masters)} filler cell masters. Running filler placement.")
    # Remove any existing fillers first before inserting new ones (safer for re-runs)
    opendp.removeFillers()
    opendp.fillerPlacement(filler_masters = filler_masters,
                                 prefix = filler_cells_prefix,
                                 verbose = False)
    print("Filler cell insertion complete.")
else:
    print("Skipping filler cell insertion.")


# Write DEF file after filler insertion
print("Writing filler.def")
design.writeDef("filler.def")

# --- Global Routing ---
print("--- Performing Global Routing ---")
grt = design.getGlobalRouter()

# Set routing layer ranges for signal and clock nets (Metal1 to Metal7)
# Find layer levels for Metal1 and Metal7
metal1 = tech.findLayer(metal1_name)
metal7 = tech.findLayer(metal7_name)

metal1_level = metal1.getRoutingLevel() if metal1 else 0
metal7_level = metal7.getRoutingLevel() if metal7 else 0

if metal1_level == 0 or metal7_level == 0 or metal1_level > metal7_level:
    print(f"Error: Could not find usable routing layers '{metal1_name}' to '{metal7_name}' for Global Routing.", file=sys.stderr)
    # Proceeding, but global routing will fail
    min_route_layer = 1 # Use default minimal level if layers not found
    max_route_layer = 10 # Use default maximal level if layers not found
else:
    min_route_layer = metal1_level
    max_route_layer = metal7_level
    print(f"Setting routing layers for signal and clock nets: {metal1_name} (level {min_route_layer}) to {metal7_name} (level {max_route_layer}).")


grt.setMinRoutingLayer(min_route_layer)
grt.setMaxRoutingLayer(max_route_layer)
# Use the same layers for clock routing as specified in prompt
grt.setMinLayerForClock(min_route_layer)
grt.setMaxLayerForClock(max_route_layer)

# Set routing adjustment (congestion control). 0.5 is a typical value.
grt.setAdjustment(0.5)
grt.setVerbose(True)

# Run global routing
# The prompt requested "Set the iteration of the global router as 20 times".
# As noted before, TritonGR doesn't have a single iteration parameter like this.
# The globalRoute() method itself might iterate internally for congestion, but we just call it once.
print("Running globalRoute.")
# Pass True to ignore DRC violations during GR (they will be fixed in DR)
grt.globalRoute(True)
print("Global Routing complete.")

# Write DEF file after global routing
print("Writing grt.def")
design.writeDef("grt.def")

# --- Detailed Routing ---
print("--- Performing Detailed Routing ---")
drter = design.getTritonRoute()
# Get default detailed routing parameters
params = drt.ParamStruct()

# Configure parameters
params.outputMazeFile = "" # Optional debug output
params.outputDrcFile = "droute.drc" # Output DRC report
params.outputCmapFile = "" # Optional debug output
params.outputGuideCoverageFile = "" # Optional debug output
params.dbProcessNode = "" # Process node information, leave empty if not needed

params.enableViaGen = True # Enable via generation
params.drouteEndIter = 1 # Number of detailed routing iterations. 1 is common for final DR.

# Set routing layer range for detailed routing (Metal1 to Metal7)
# Use the same layers as global routing
bottom_dr_layer = tech.findLayer(metal1_name)
top_dr_layer = tech.findLayer(metal7_name)

if not bottom_dr_layer or not top_dr_layer:
     print(f"Error: Could not find detailed routing layers '{metal1_name}' or '{metal7_name}'.", file=sys.stderr)
     # Proceeding, but DR will likely fail

params.bottomRoutingLayer = metal1_name if bottom_dr_layer else "" # Use layer name string
params.topRoutingLayer = metal7_name if top_dr_layer else ""

params.verbose = 1 # Enable verbose output
params.cleanPatches = True # Clean up fill/patch shapes after routing
params.doPa = True # Perform post-route metal filling (Patch Abutment)
params.singleStepDR = False # Run DR in a single step (usually False)
params.minAccessPoints = 1 # Minimum access points for routing (common setting)
params.saveGuideUpdates = False # Do not save guide updates

# Set the configured parameters
drter.setParams(params)
# Run detailed routing
print("Running TritonRoute.")
drter.main()
print("Detailed Routing complete.")


# Write final DEF file after detailed routing
print("Writing final.def")
design.writeDef("final.def")

# Write final Verilog file
print("Writing final.v")
design.evalTclString("write_verilog final.v")

print("OpenROAD flow complete.")
sys.exit(0) # Exit successfully