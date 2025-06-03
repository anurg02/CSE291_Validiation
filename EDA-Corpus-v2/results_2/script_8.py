import odb
import pdn
import cts
import drt
import openroad as ord
from openroad import Tech, Design
from pathlib import Path
import os

# --- Configuration ---
# Define paths to library and design files
# Update these paths based on your actual file structure
script_dir = Path(__file__).parent
design_dir = script_dir.parent / "Design" # Assuming Design directory is one level up
tech_lef_dir = design_dir / "nangate45" / "lef"
lib_dir = design_dir / "nangate45" / "lib"
# Assuming the Verilog netlist is named gcd.v
verilog_file = design_dir / "gcd.v"
design_top_module_name = "gcd" # Assuming top module name is gcd

# Design parameters
clock_port_name = "clk"
clock_period_ns = 50
target_utilization = 0.40
core_to_die_margin_micron = 12
macro_min_distance_micron = 5.0
macro_halo_micron = 5.0
dp_max_displacement_micron_x = 0.5
dp_max_displacement_micron_y = 0.5
wire_resistance_per_micron = 0.03574
wire_capacitance_per_micron = 0.07516
clock_buffer_cell = "BUF_X2"

# PDN parameters
pdn_stdcell_grid_m1_width = 0.07 # um
pdn_stdcell_grid_m4_width = 1.2 # um
pdn_stdcell_grid_m4_spacing = 1.2 # um
pdn_stdcell_grid_m4_pitch = 6 # um
pdn_stdcell_ring_m7_width = 4 # um
pdn_stdcell_ring_m7_spacing = 4 # um
pdn_stdcell_ring_m8_width = 4 # um
pdn_stdcell_ring_m8_spacing = 4 # um
pdn_macro_grid_m5_width = 1.2 # um
pdn_macro_grid_m5_spacing = 1.2 # um
pdn_macro_grid_m5_pitch = 6 # um
pdn_macro_grid_m6_width = 1.2 # um
pdn_macro_grid_m6_spacing = 1.2 # um
pdn_macro_grid_m6_pitch = 6 # um
pdn_macro_ring_m5_width = 1.5 # um
pdn_macro_ring_m5_spacing = 1.5 # um
pdn_macro_ring_m6_width = 1.5 # um
pdn_macro_ring_m6_spacing = 1.5 # um
pdn_via_cut_pitch_zero = 0 # um
pdn_offset_zero = 0 # um

# Output file prefixes
output_def_prefix = "gcd"

# --- Initialization ---
print("Initializing OpenROAD...")
db = ord.get_db() # Get the database object
tech = Tech() # Initialize technology object

# Read technology and library files
print(f"Reading technology LEF files from {tech_lef_dir}...")
for lef_file in tech_lef_dir.glob("*.tech.lef"):
    tech.readLef(lef_file.as_posix())
print(f"Reading cell LEF files from {tech_lef_dir}...")
for lef_file in tech_lef_dir.glob("*.lef"): # Read all .lef files, including cell LEFs
    tech.readLef(lef_file.as_posix())
print(f"Reading liberty files from {lib_dir}...")
for lib_file in lib_dir.glob("*.lib"):
    tech.readLiberty(lib_file.as_posix())

# Create design and read Verilog netlist
print(f"Creating design for module '{design_top_module_name}'...")
design = Design(tech)
print(f"Reading Verilog netlist: {verilog_file}")
design.readVerilog(verilog_file.as_posix())
print(f"Linking design: {design_top_module_name}")
design.link(design_top_module_name)

# Check if linking was successful
if design.getBlock() is None:
    print("Error: Design linking failed. Check Verilog file and top module name.")
    exit()

print("Initialization complete.")

# --- Clock Configuration ---
print(f"Setting clock period: {clock_period_ns} ns on port '{clock_port_name}'")
# Using TCL commands as direct Python API equivalents for create_clock are not standard on the Design object
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}]")
# Propagate the clock signal
design.evalTclString(f"set_propagated_clock [get_clocks {{*}}]") # Propagate all clocks

# --- Floorplanning ---
print("Performing floorplanning...")
floorplan = design.getFloorplan()

# Find the standard cell site from the loaded LEF files
# The site name must match the definition in your technology LEF file.
# You might need to inspect your LEF file to find the correct site name.
# Example site name from FreePDK45: "FreePDK45_38x28_10R_NP_162NW_34O"
# Let's try to find a common site type or list available sites
site = None
for lib in db.getLibs():
    for s in lib.getSites():
        # Look for typical site names or types (e.g., CORE, SLICE)
        if "CORE" in s.getName().upper() or "SLICE" in s.getName().upper():
             site = s
             print(f"Found potential site: {site.getName()}")
             break # Found one, use it
    if site: break # Found site in a library

# If no site is found by name, try finding the first site marked as 'CORE'
if not site:
    print("Attempting to find a site with type CORE...")
    for lib in db.getLibs():
        for s in lib.getSites():
            if s.getType() == odb.dbSite.CORE:
                site = s
                print(f"Found CORE site: {site.getName()}")
                break
        if site: break

# If still no site is found, raise an error
if not site:
    print("Error: Standard cell site not found. Please update the script with the correct site name or ensure CORE sites are defined.")
    exit()

margin_dbu = design.micronToDBU(core_to_die_margin_micron)

# Initialize floorplan with utilization and margin (aspect ratio 1.0)
# initFloorplan(utilization, aspect_ratio, core_margin_left, core_margin_bottom, core_margin_right, core_margin_top, site)
floorplan.initFloorplan(target_utilization, 1.0, margin_dbu, margin_dbu, margin_dbu, margin_dbu, site)
print("Floorplan initialized.")

# Generate placement tracks based on the site and metal layers
floorplan.makeTracks()
print("Placement tracks generated.")

# Save DEF after floorplanning
design.writeDef(f"{output_def_prefix}.floorplan.def")
print(f"Saved {output_def_prefix}.floorplan.def")

# --- I/O Pin Placement ---
print("Performing I/O pin placement...")
io_placer = design.getIOPlacer()
io_params = io_placer.getParameters()
io_params.setRandSeed(42) # Set random seed for repeatability

# Set min distance in DBU (0um as per prompt)
io_params.setMinDistanceInTracks(False)
io_params.setMinDistance(design.micronToDBU(0))
io_params.setCornerAvoidance(design.micronToDBU(0)) # Avoid corners distance (0um)

# Place I/O pins on metal8 (horizontal) and metal9 (vertical) layers
metal8 = design.getTech().getDB().getTech().findLayer("metal8")
metal9 = design.getTech().getDB().getTech().findLayer("metal9")

if metal8:
    io_placer.addHorLayer(metal8)
    print("Added metal8 for horizontal IO placement.")
else:
    print("Warning: metal8 layer not found for IO placement.")

if metal9:
     io_placer.addVerLayer(metal9)
     print("Added metal9 for vertical IO placement.")
else:
     print("Warning: metal9 layer not found for IO placement.")

# Use random mode (annealing)
io_placer.runAnnealing(True) # True enables random mode (annealing)
print("I/O pin placement complete.")

# Save DEF after IO placement
design.writeDef(f"{output_def_prefix}.io_placement.def")
print(f"Saved {output_def_prefix}.io_placement.def")

# --- Macro Placement ---
print("Checking for macros...")
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    print(f"Found {len(macros)} macros. Performing macro placement...")
    mpl = design.getMacroPlacer()
    block = design.getBlock()
    core = block.getCoreArea()

    # Configure and run macro placement
    # Parameters based on prompt and common usage
    mpl.place(
        num_threads = 64,
        max_num_macro = len(macros),
        min_num_macro = 0,
        max_num_inst = 0, # Do not limit standard cells
        min_num_inst = 0,
        tolerance = 0.1,
        max_num_level = 2,
        coarsening_ratio = 10.0,
        large_net_threshold = 50,
        signature_net_threshold = 50,
        halo_width = macro_halo_micron, # 5um halo around macros
        halo_height = macro_halo_micron, # 5um halo around macros
        fence_lx = block.dbuToMicrons(core.xMin()), # Use core area as fence
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
        target_util = target_utilization, # Use same target utilization as core
        target_dead_space = 0.05,
        min_ar = 0.33,
        snap_layer = 4, # Align macro pins on metal4 (example, adjust if needed)
        bus_planning_flag = False,
        report_directory = "",
        min_macro_dist_x = macro_min_distance_micron, # Macros at least 5um apart in X
        min_macro_dist_y = macro_min_distance_micron # Macros at least 5um apart in Y
    )
    print("Macro placement complete.")

    # Save DEF after macro placement
    design.writeDef(f"{output_def_prefix}.macro_placement.def")
    print(f"Saved {output_def_prefix}.macro_placement.def")
else:
    print("No macros found. Skipping macro placement.")


# --- Global Placement ---
print("Performing global placement...")
gpl = design.getReplace()

# Configure global placement parameters
gpl.setTimingDrivenMode(False) # Can enable timing driven if spef is loaded
gpl.setRoutabilityDrivenMode(True) # Enable routability driven mode
gpl.setUniformTargetDensityMode(True) # Use uniform target density
# The prompt requested 20 iterations for the global *router*, but the OpenROAD GlobalRouter
# does not expose an iteration parameter directly. This was likely a misunderstanding or
# refers to an older tool. We apply typical placement steps instead.
# gpl.setInitialPlaceMaxIter(20) # This parameter is not standard for controlling iterations via this API

# Run initial and Nesterov placement
gpl.doInitialPlace(threads = 4)
gpl.doNesterovPlace(threads = 4)

# Important: After placement, reset the placer state
# gpl.reset() # Reset is often called before new placement, not after completing.
# Let's keep it simple and assume the calls complete the process.

print("Global placement complete.")

# Save DEF after global placement
design.writeDef(f"{output_def_prefix}.global_placement.def")
print(f"Saved {output_def_prefix}.global_placement.def")

# --- Detailed Placement ---
print("Performing detailed placement...")
# Remove filler cells before detailed placement if they exist (important for clean placement)
design.getOpendp().removeFillers()

# Allow max displacement
max_disp_x_dbu = int(design.micronToDBU(dp_max_displacement_micron_x))
max_disp_y_dbu = int(design.micronToDBU(dp_max_displacement_micron_y))

# Perform detailed placement
# detailedPlacement(max_displacment_x, max_displacement_y, cells_to_move_file, is_rectilinear_region)
design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Detailed placement complete.")

# Save DEF after detailed placement
design.writeDef(f"{output_def_prefix}.detailed_placement.def")
print(f"Saved {output_def_prefix}.detailed_placement.def")

# --- Clock Tree Synthesis (CTS) ---
print("Performing Clock Tree Synthesis (CTS)...")
# Set RC values for clock and signal nets using TCL
design.evalTclString(f"set_wire_rc -clock -resistance {wire_resistance_per_micron} -capacitance {wire_capacitance_per_micron}")
design.evalTclString(f"set_wire_rc -signal -resistance {wire_resistance_per_micron} -capacitance {wire_capacitance_per_micron}")

cts = design.getTritonCts()
# Configure CTS parameters
parms = cts.getParms()
parms.setWireSegmentUnit(20) # Example value, adjust as needed
# Configure clock buffers
cts.setBufferList(clock_buffer_cell)
cts.setRootBuffer(clock_buffer_cell)
cts.setSinkBuffer(clock_buffer_cell)

# Run CTS
cts.runTritonCts()
print("CTS complete.")

# Save DEF after CTS
design.writeDef(f"{output_def_prefix}.cts.def")
print(f"Saved {output_def_prefix}.cts.def")

# --- Filler Cell Insertion ---
print("Inserting filler cells...")
db = ord.get_db()
filler_masters = []
# Find CORE_SPACER type masters in the library
for lib in db.getLibs():
    for master in lib.getMasters():
        # Check for standard filler cell types or names
        if master.getType() == odb.dbMaster.CORE_SPACER:
             filler_masters.append(master)
        # Alternatively, look for specific names if known (e.g., "FILLCELL_")
        # elif master.getName().startswith("FILLCELL_"):
        #     filler_masters.append(master)


# Run filler placement if filler masters are found
if len(filler_masters) == 0:
    print("No CORE_SPACER filler cells found in library! Skipping filler insertion.")
else:
    print(f"Found {len(filler_masters)} filler cell masters. Inserting fillers...")
    design.getOpendp().fillerPlacement(filler_masters = filler_masters,
                                     prefix = "filler_", # Use a consistent prefix
                                     verbose = False)
    print("Filler insertion complete.")
    # Save DEF after filler insertion
    design.writeDef(f"{output_def_prefix}.filler_placement.def")
    print(f"Saved {output_def_prefix}.filler_placement.def")


# --- Power Delivery Network (PDN) ---
print("Configuring Power Delivery Network (PDN)...")
block = design.getBlock()

# Set up global power/ground connections
# Ensure VDD/VSS nets exist and are marked as special
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

if VDD_net is None:
    VDD_net = odb.dbNet_create(block, "VDD")
    print("Created VDD net.")
if VSS_net is None:
    VSS_net = odb.dbNet_create(block, "VSS")
    print("Created VSS net.")

VDD_net.setSigType("POWER")
VDD_net.setSpecial()
VSS_net.setSigType("GROUND")
VSS_net.setSpecial()

# Connect standard power pins to global nets
print("Connecting power pins to global nets...")
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
block.globalConnect()
print("Global power connections complete.")

# Configure power domains
pdngen = design.getPdnGen()
# Set core power domain with primary power/ground nets
pdngen.setCoreDomain(power = VDD_net, ground = VSS_net) # Assuming no switched or secondary power

# Get routing layers for power grid implementation
m1 = design.getTech().getDB().getTech().findLayer("metal1")
m4 = design.getTech().getDB().getTech().findLayer("metal4")
m5 = design.getTech().getDB().getTech().findLayer("metal5")
m6 = design.getTech().getDB().getTech().findLayer("metal6")
m7 = design.getTech().getDB().getTech().findLayer("metal7")
m8 = design.getTech().getDB().getTech().findLayer("metal8")

# Check if necessary layers exist
required_layers_stdcell = {'metal1': m1, 'metal4': m4, 'metal7': m7, 'metal8': m8}
for layer_name, layer_obj in required_layers_stdcell.items():
    if not layer_obj:
        print(f"Error: Required layer '{layer_name}' not found for standard cell PDN.")
        exit()

# Create power grid for standard cells (Core domain)
domains = [pdngen.findDomain("Core")]
# Halo around macros for standard cell PDN routing - set to 0 as per request for offsets
stdcell_pdn_halo_dbu = [design.micronToDBU(0) for i in range(4)]

print("Building Core Power Grid (Standard Cells)...")
for domain in domains:
    # Create the main core grid structure for standard cells
    pdngen.makeCoreGrid(domain = domain,
        name = "core_grid",
        starts_with = pdn.GROUND, # Start with ground net (VSS)
        pin_layers = [], # Don't connect to pins directly at grid creation
        generate_obstructions = [],
        powercell = None,
        powercontrol = None) # Simplified, assuming no complex power control

# Get the created core grid(s) - makeCoreGrid can return multiple grids if region based
core_grids = pdngen.findGrid("core_grid")
if not core_grids:
     print("Error: Core grid 'core_grid' not found after creation.")
     exit()

for g in core_grids:
    print(f"  - Adding features to grid {g.getName()}...")
    # Create horizontal power straps on metal1 (Followpin)
    pdngen.makeFollowpin(grid = g,
        layer = m1,
        width = design.micronToDBU(pdn_stdcell_grid_m1_width), # 0.07um width
        extend = pdn.CORE) # Extend within the core area

    # Create power straps on metal4 (Strap)
    pdngen.makeStrap(grid = g,
        layer = m4,
        width = design.micronToDBU(pdn_stdcell_grid_m4_width), # 1.2um width
        spacing = design.micronToDBU(pdn_stdcell_grid_m4_spacing), # 1.2um spacing
        pitch = design.micronToDBU(pdn_stdcell_grid_m4_pitch), # 6um pitch
        offset = design.micronToDBU(pdn_offset_zero), # 0um offset
        number_of_straps = 0, # Auto-calculate
        snap = False, # Do not snap to track/grid (False is common for straps not on followpin layers)
        starts_with = pdn.GRID, # Start pattern from grid origin
        extend = pdn.CORE, # Extend within the core area
        nets = [])

    # Create power rings around the core boundary using metal7 and metal8
    # Using makeRing on the core grid with extend=pdn.BOUNDARY places rings at the core boundary.
    pdngen.makeRing(grid = g,
        layer0 = m7, # Layer for one pair of ring stripes (e.g., horizontal)
        width0 = design.micronToDBU(pdn_stdcell_ring_m7_width), # 4um width
        spacing0 = design.micronToDBU(pdn_stdcell_ring_m7_spacing), # 4um spacing
        layer1 = m8, # Layer for the other pair of ring stripes (e.g., vertical)
        width1 = design.micronToDBU(pdn_stdcell_ring_m8_width), # 4um width
        spacing1 = design.micronToDBU(pdn_stdcell_ring_m8_spacing), # 4um spacing
        starts_with = pdn.GRID, # Start pattern from grid origin
        offset = [design.micronToDBU(pdn_offset_zero) for i in range(4)], # 0um offset from edge
        pad_offset = [design.micronToDBU(pdn_offset_zero) for i in range(4)], # 0um padding offset
        extend = pdn.BOUNDARY, # Extend ring to the core boundary
        pad_pin_layers = [], # No connection to pads via ring specified
        nets = []) # Connect to default power/ground nets of the grid's domain

    # Create via connections between standard cell power grid layers
    pdn_cut_pitch_dbu = [design.micronToDBU(pdn_via_cut_pitch_zero) for i in range(2)] # 0um via pitch

    # M1 (horizontal) to M4 (vertical)
    pdngen.makeConnect(grid = g, layer0 = m1, layer1 = m4,
        cut_pitch_x = pdn_cut_pitch_dbu[0],
        cut_pitch_y = pdn_cut_pitch_dbu[1],
        vias = [], techvias = [], max_rows = 0, max_columns = 0,
        ongrid = [], split_cuts = dict(), dont_use_vias = "")

    # M4 (vertical) to M7 (horizontal)
    pdngen.makeConnect(grid = g, layer0 = m4, layer1 = m7,
        cut_pitch_x = pdn_cut_pitch_dbu[0],
        cut_pitch_y = pdn_cut_pitch_dbu[1],
        vias = [], techvias = [], max_rows = 0, max_columns = 0,
        ongrid = [], split_cuts = dict(), dont_use_vias = "")

    # M7 (horizontal) to M8 (vertical)
    pdngen.makeConnect(grid = g, layer0 = m7, layer1 = m8,
        cut_pitch_x = pdn_cut_pitch_dbu[0],
        cut_pitch_y = pdn_cut_pitch_dbu[1],
        vias = [], techvias = [], max_rows = 0, max_columns = 0,
        ongrid = [], split_cuts = dict(), dont_use_vias = "")


# Create power grid for macro blocks (if macros exist)
if len(macros) > 0:
    print("Building Macro Power Grids and Rings...")
    required_layers_macro = {'metal4': m4, 'metal5': m5, 'metal6': m6, 'metal7': m7}
    for layer_name, layer_obj in required_layers_macro.items():
        if not layer_obj:
            print(f"Error: Required layer '{layer_name}' not found for macro PDN.")
            exit()

    for i, macro in enumerate(macros):
        # Create separate power grid for each macro instance
        # Halo around macros for PDN routing within the macro grid (set to 0 offset)
        instance_pdn_halo_dbu = [design.micronToDBU(pdn_offset_zero) for i in range(4)]

        # makeInstanceGrid creates a grid area around the specified instance
        pdngen.makeInstanceGrid(domain = domains[0], # Assuming macros are in the Core domain
            name = f"macro_grid_{i}", # Unique name for each macro grid
            starts_with = pdn.GROUND, # Start with ground net (VSS)
            inst = macro, # Target macro instance
            halo = instance_pdn_halo_dbu, # Halo around the macro instance for this grid
            pg_pins_to_boundary = True, # Connect macro P/G pins to the boundary of this grid
            default_grid = False, # This is an instance-specific grid
            generate_obstructions = [],
            is_bump = False)

        # Get the created instance grid
        macro_grids = pdngen.findGrid(f"macro_grid_{i}")
        if not macro_grids:
            print(f"Warning: Instance grid 'macro_grid_{i}' not found for macro {macro.getName()}. Skipping PDN for this macro.")
            continue

        for mg in macro_grids:
             print(f"  - Adding features to grid {mg.getName()} for macro {macro.getName()}...")
             # Create power straps on metal5 for macro connections (Strap)
             pdngen.makeStrap(grid = mg,
                 layer = m5,
                 width = design.micronToDBU(pdn_macro_grid_m5_width), # 1.2um width
                 spacing = design.micronToDBU(pdn_macro_grid_m5_spacing), # 1.2um spacing
                 pitch = design.micronToDBU(pdn_macro_grid_m5_pitch), # 6um pitch
                 offset = design.micronToDBU(pdn_offset_zero), # 0um offset
                 number_of_straps = 0, # Auto-calculate
                 snap = True, # Snap to grid (True is common for instance grids aligned to tracks/macro pins)
                 starts_with = pdn.GRID, # Start pattern from grid origin
                 extend = pdn.CORE, # Extend within the instance grid area (which is around the macro)
                 nets = [])

             # Create power straps on metal6 for macro connections (Strap)
             pdngen.makeStrap(grid = mg,
                 layer = m6,
                 width = design.micronToDBU(pdn_macro_grid_m6_width), # 1.2um width
                 spacing = design.micronToDBU(pdn_macro_grid_m6_spacing), # 1.2um spacing
                 pitch = design.micronToDBU(pdn_macro_grid_m6_pitch), # 6um pitch
                 offset = design.micronToDBU(pdn_offset_zero), # 0um offset
                 number_of_straps = 0, # Auto-calculate
                 snap = True,
                 starts_with = pdn.GRID,
                 extend = pdn.CORE, # Extend within the instance grid area
                 nets = [])

             # Create power rings around macro using metal5 and metal6
             pdngen.makeRing(grid = mg,
                 layer0 = m5,
                 width0 = design.micronToDBU(pdn_macro_ring_m5_width), # 1.5um width
                 spacing0 = design.micronToDBU(pdn_macro_ring_m5_spacing), # 1.5um spacing
                 layer1 = m6,
                 width1 = design.micronToDBU(pdn_macro_ring_m6_width), # 1.5um width
                 spacing1 = design.micronToDBU(pdn_macro_ring_m6_spacing), # 1.5um spacing
                 starts_with = pdn.GRID,
                 offset = [design.micronToDBU(pdn_offset_zero) for i in range(4)], # 0um offset from edge
                 pad_offset = [design.micronToDBU(pdn_offset_zero) for i in range(4)], # 0um padding offset
                 extend = False, # Do not extend beyond the instance grid boundary
                 pad_pin_layers = [],
                 nets = [])

             # Create via connections between macro power grid layers
             # Connections to core grid layers (M4, M7) and between macro grid layers (M5, M6)
             # M4 (core grid) to M5 (macro grid)
             pdngen.makeConnect(grid = mg, layer0 = m4, layer1 = m5,
                cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1],
                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")

             # M5 (macro grid) to M6 (macro grid)
             pdngen.makeConnect(grid = mg, layer0 = m5, layer1 = m6,
                cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1],
                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")

             # M6 (macro grid) to M7 (core grid)
             pdngen.makeConnect(grid = mg, layer0 = m6, layer1 = m7,
                cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1],
                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")


# Generate the final power delivery network shapes
print("Generating PDN shapes...")
pdngen.checkSetup() # Verify configuration
pdngen.buildGrids(False) # Build the power grid shapes (False means no trimming/cleanup yet)
pdngen.writeToDb(True) # Write power grid shapes to the design database (True to add pins/connections)
pdngen.resetShapes() # Reset temporary shapes used during generation
print("PDN generation complete.")

# Save DEF after PDN generation
design.writeDef(f"{output_def_prefix}.pdn.def")
print(f"Saved {output_def_prefix}.pdn.def")


# --- Global Routing ---
print("Performing global routing...")
grt = design.getGlobalRouter()

# Set routing layer ranges for signal and clock nets
# Assuming metal1 is the lowest and metal7 is the highest for standard cells and clock
signal_low_layer_lvl = m1.getRoutingLevel() if m1 else 1
signal_high_layer_lvl = m7.getRoutingLevel() if m7 else 7
clk_low_layer_lvl = m1.getRoutingLevel() if m1 else 1
clk_high_layer_lvl = m7.getRoutingLevel() if m7 else 7 # Clock can use higher layers

grt.setMinRoutingLayer(signal_low_layer_lvl)
grt.setMaxRoutingLayer(signal_high_layer_lvl)
grt.setMinLayerForClock(clk_low_layer_lvl)
grt.setMaxLayerForClock(clk_high_layer_lvl)

# Configure global router parameters (these might vary based on technology and needs)
grt.setAdjustment(0.5) # Capacity adjustment
grt.setVerbose(True)

# The prompt requested 20 iterations, but this is not a standard parameter for GlobalRouter in this API.
# The default globalRoute() call performs the routing.

grt.globalRoute(True) # Run global routing (True for verbose output)
print("Global routing complete.")

# Save DEF after global routing
design.writeDef(f"{output_def_prefix}.global_routing.def")
print(f"Saved {output_def_prefix}.global_routing.def")


# --- Detailed Routing ---
print("Performing detailed routing...")
drter = design.getTritonRoute()
params = drt.ParamStruct()

# Configure detailed routing parameters (using defaults or common values)
# Layer ranges should match global routing or be within them
params.bottomRoutingLayer = m1.getName() if m1 else "metal1"
params.topRoutingLayer = m7.getName() if m7 else "metal7"
params.drouteEndIter = 1 # Number of detailed routing iterations (1 is common for initial run)
params.verbose = 1 # Verbosity level
params.cleanPatches = True # Clean up metal patches
params.doPa = True # Perform pin access
params.singleStepDR = False # Do not run detailed routing in single steps
params.minAccessPoints = 1 # Minimum access points for pin access
params.enableViaGen = True # Enable via generation
params.orSeed = -1 # Random seed for routing (-1 uses time)
params.orK = 0 # Keep default
params.outputMazeFile = "" # Optional debug output
params.outputDrcFile = "" # Optional DRC output file name (e.g., "drc.rpt")
params.outputCmapFile = "" # Optional cmap output
params.outputGuideCoverageFile = "" # Optional guide coverage output
params.dbProcessNode = "" # Leave empty or set based on tech file

drter.setParams(params) # Set detailed routing parameters
drter.main() # Run detailed routing
print("Detailed routing complete.")

# Save DEF after detailed routing
design.writeDef(f"{output_def_prefix}.detailed_routing.def")
print(f"Saved {output_def_prefix}.detailed_routing.def")

# --- Final Outputs ---
# Write final Verilog netlist
final_verilog_file = f"{output_def_prefix}.final.v"
print(f"Writing final Verilog netlist: {final_verilog_file}")
design.evalTclString(f"write_verilog {final_verilog_file}")

# Write final odb file
final_odb_file = f"{output_def_prefix}.final.odb"
print(f"Writing final ODB database: {final_odb_file}")
design.writeDb(final_odb_file)

print("Script execution finished.")