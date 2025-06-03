# This script is a consolidation and refinement based on the user's request and the provided Gemini draft.
# It implements the specified OpenROAD flow, focusing on correct API usage,
# proper sequence of steps, and adherence to the requirements outlined in the prompt.

# --- Imports ---
from openroad import Tech, Design, Timing
from pathlib import Path
import odb
import pdn
import openroad as ord
import drt
import psm # Power grid analysis

# --- User Configuration ---
# Set paths to library and design files
# !!! REPLACE THESE WITH YOUR ACTUAL PATHS !!!
# Example:
# design_dir = Path("path/to/your/design")
# libDir = design_dir / "lib" / "nangate45"
# lefDir = design_dir / "lef" / "nangate45"
# verilog_file_path = design_dir / "verilog" / "my_design.v"
# top_module_name = "my_design"
libDir = Path("../Design/nangate45/lib") # Example path - replace with actual path
lefDir = Path("../Design/nangate45/lef") # Example path - replace with actual path
verilog_file_path = Path("../Design/my_design.v") # Example path - replace with actual path
top_module_name = "my_design" # Replace with the actual top module name

# Clock configuration
clock_port_name = "clk_i"
clock_period_ns = 40.0
clock_name = "core_clock" # Internal clock name used in OpenROAD

# Floorplan configuration
floorplan_utilization = 0.35
# floorplan_aspect_ratio = 1.0 # Default 1.0 is often used if not specified
floorplan_margin_um = 10.0 # Spacing between core and die boundary
# Example site name - REPLACE if needed based on your LEF files
# Find a CORE_SPACER site name in your LEF, e.g., FreePDK45_38x28_10R_NP_162NW_34O
floorplan_site_name = "FreePDK45_38x28_10R_NP_162NW_34O"

# IO Placement configuration
io_horizontal_layer_name = "metal8" # Pins on M8 (horizontal)
io_vertical_layer_name = "metal9" # Pins on M9 (vertical)
# io_min_distance_um = 0.0 # Default 0 in API, keeps requested minimum distance of 0
# io_corner_avoidance_um = 0.0 # Default 0 in API

# Macro Placement configuration
macro_halo_um = 5.0 # Halo region around each macro
# macro_min_spacing_um = 5.0 # Requested min spacing - addressed by halo, not a direct parameter

# Placement configuration
global_placement_iterations = 30 # Iterations for initial global placement
detailed_placement_max_disp_x_um = 0.0 # Max displacement X for detailed placement
detailed_placement_max_disp_y_um = 0.0 # Max displacement Y for detailed placement

# CTS configuration
cts_buffer_cell_name = "BUF_X3" # Clock buffer cell to use
wire_rc_resistance = 0.0435 # Unit resistance for clock and signal wires
wire_rc_capacitance = 0.0817 # Unit capacitance for clock and signal wires

# PDN configuration (all dimensions in microns)
# Standard cell power grid layers and dimensions
std_cell_ring_m7_width_um = 5.0
std_cell_ring_m7_spacing_um = 5.0
std_cell_ring_m8_width_um = 5.0
std_cell_ring_m8_spacing_um = 5.0

std_cell_strap_m1_width_um = 0.07
std_cell_strap_m4_width_um = 1.2
std_cell_strap_m4_spacing_um = 1.2
std_cell_strap_m4_pitch_um = 6.0
std_cell_strap_m7_width_um = 1.4
std_cell_strap_m7_spacing_um = 1.4
std_cell_strap_m7_pitch_um = 10.8
# M8 straps are not specified in the prompt beyond rings, only M7 straps are detailed with pitch

# Macro power grid layers and dimensions (same dimensions for rings and straps as per prompt phrasing for M5/M6 grid)
macro_m5_width_um = 1.2
macro_m5_spacing_um = 1.2
macro_m5_pitch_um = 6.0
macro_m6_width_um = 1.2
macro_m6_spacing_um = 1.2
macro_m6_pitch_um = 6.0

# Via configuration
pdn_via_cut_pitch_um = 2.0 # Pitch for via arrays between parallel grids
pdn_offset_um = 0.0 # Offset for all PDN structures relative to origin/grid

# IR Drop analysis configuration
ir_drop_analysis_net_name = "VDD" # Net to analyze IR drop on (e.g., VDD or VSS)

# Routing configuration
routing_bottom_layer_name = "metal1" # Bottom layer for routing
routing_top_layer_name = "metal6" # Top layer for routing

# Output files
output_def_file = "final.def" # Final output DEF file
output_power_report = "power_report.rpt" # Power report file
output_ir_report = "ir_drop_report.rpt" # IR drop report file

# --- Flow Execution ---

# Get database object - essential for accessing technology and design data
db = ord.get_db()

# Initialize OpenROAD objects and read technology files
print("INFO: Initializing OpenROAD and reading tech files...")
tech = Tech()

# Read all liberty (.lib) and LEF files from the library directories
libFiles = list(libDir.glob("*.lib"))
techLefFiles = list(lefDir.glob("*.tech.lef"))
lefFiles = list(lefDir.glob('*.lef'))

if not libFiles:
    print(f"ERROR: No .lib files found in {libDir}")
    exit(1)
if not techLefFiles and not lefFiles:
     print(f"ERROR: No .lef files found in {lefDir}")
     exit(1)

# Load liberty timing libraries
for libFile in libFiles:
  print(f"INFO: Reading liberty file: {libFile.name}")
  tech.readLiberty(libFile.as_posix())
# Load technology and cell LEF files
for techLefFile in techLefFiles:
  print(f"INFO: Reading tech LEF file: {techLefFile.name}")
  tech.readLef(techLefFile.as_posix())
for lefFile in lefFiles:
  print(f"INFO: Reading cell LEF file: {lefFile.name}")
  tech.readLef(lefFile.as_posix())

# Create design and read Verilog netlist
print(f"INFO: Reading Verilog file: {verilog_file_path.name}")
design = Design(tech)
if not verilog_file_path.exists():
     print(f"ERROR: Verilog file not found: {verilog_file_path}")
     exit(1)
design.readVerilog(verilog_file_path.as_posix())

print(f"INFO: Linking design with top module: {top_module_name}")
try:
    design.link(top_module_name) # Link the top module
except Exception as e:
    print(f"ERROR: Failed to link design. Ensure '{top_module_name}' is the correct top module name and libraries are correct.")
    print(f"Error details: {e}")
    exit(1)

if design.getBlock() is None:
    print(f"ERROR: Design block is not created after linking. Check Verilog and library files.")
    exit(1)

# Configure clock constraints
print(f"INFO: Setting clock '{clock_name}' on port '{clock_port_name}' with period {clock_period_ns} ns.")
# Find the clock port to ensure it exists
if design.getBlock().findPort(clock_port_name) is None:
     print(f"ERROR: Clock port '{clock_port_name}' not found in the design.")
     exit(1)
# Create clock signal
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
# Set the clock signal as propagated (important for CTS and timing analysis later)
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Initialize floorplan with utilization and margins
print(f"INFO: Initializing floorplan with utilization {floorplan_utilization} and core-to-die margin {floorplan_margin_um} um.")
floorplan = design.getFloorplan()
# Find the site definition
site = db.getTech().findSite(floorplan_site_name)
if site is None:
    print(f"ERROR: Site '{floorplan_site_name}' not found in LEF files. Please check your LEF files and 'floorplan_site_name' configuration.")
    exit(1) # Exit if site is not found

# Convert margin from microns to DBU
margin_dbu = design.micronToDBU(floorplan_margin_um)

# Initialize floorplan using utilization, aspect ratio (default 1.0), and margin
# initFloorplan(utilization, aspect_ratio, core_margin_left, core_margin_bottom, core_margin_right, core_margin_top, site)
floorplan.initFloorplan(floorplan_utilization, 1.0, margin_dbu, margin_dbu, margin_dbu, margin_dbu, site)
# Generate routing tracks based on the site
floorplan.makeTracks()

# Configure and run I/O pin placement
print(f"INFO: Placing IO pins on layers {io_horizontal_layer_name} and {io_vertical_layer_name}.")
io_placer = design.getIOPlacer()
io_params = io_placer.getParameters()
io_params.setRandSeed(42) # Set random seed for reproducibility

# Find IO placement layers using db object for consistency
hor_layer = db.getTech().findLayer(io_horizontal_layer_name)
ver_layer = db.getTech().findLayer(io_vertical_layer_name)

if hor_layer is None:
    print(f"ERROR: Horizontal IO layer '{io_horizontal_layer_name}' not found in technology LEF.")
    exit(1)
if ver_layer is None:
    print(f"ERROR: Vertical IO layer '{io_vertical_layer_name}' not found in technology LEF.")
    exit(1)

# Add layers to IO placer
io_placer.addHorLayer(hor_layer)
io_placer.addVerLayer(ver_layer)

# Set minimum distance between pins to 0 as seen in examples
io_params.setMinDistanceInTracks(False) # Set minimum distance in DBU, not tracks
io_params.setMinDistance(design.micronToDBU(0))
# Set corner avoidance distance to 0 as seen in examples
io_params.setCornerAvoidance(design.micronToDBU(0))

# Run IO placement using annealing (True for random mode as seen in examples)
io_placer.runAnnealing(True)

# Place macro blocks if present
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
if len(macros) > 0:
    print(f"INFO: Found {len(macros)} macros. Running macro placement with {macro_halo_um} um halo.")
    mpl = design.getMacroPlacer()
    block = design.getBlock()
    core = block.getCoreArea()

    # Fence region is typically the core area
    fence_lx_dbu = core.xMin()
    fence_ly_dbu = core.yMin()
    fence_ux_dbu = core.xMax()
    fence_uy_dbu = core.yMax()
    # Macro placer API expects fence in microns
    fence_lx_um = block.dbuToMicrons(fence_lx_dbu)
    fence_ly_um = block.dbuToMicrons(fence_ly_dbu)
    fence_ux_um = block.dbuToMicrons(fence_ux_dbu)
    fence_uy_um = block.dbuToMicrons(fence_uy_dbu)

    # Place macros with specified halo and fence (using microns as required by API)
    # Note: The API requires halo in microns
    mpl.place(
        num_threads = 4, # Using a reasonable number of threads
        max_num_macro = len(macros), # Place all macros
        min_num_macro = 0, # Place at least 0
        max_num_inst = 0, # Do not limit std cell placement by macro placer
        min_num_inst = 0, # Do not require std cells to be placed by macro placer
        tolerance = 0.1, # Example value
        max_num_level = 2, # Example value
        coarsening_ratio = 10.0, # Example value
        large_net_threshold = 50, # Example value
        signature_net_threshold = 50, # Example value
        halo_width = macro_halo_um, # Halo specified in microns
        halo_height = macro_halo_um, # Halo specified in microns
        fence_lx = fence_lx_um, # Fence specified in microns
        fence_ly = fence_ly_um,
        fence_ux = fence_ux_um,
        fence_uy = fence_uy_um,
        # Example weights - these can be tuned
        area_weight = 0.1,
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        pin_access_th = 0.0,
        target_util = 0.25, # Example - may need tuning
        target_dead_space = 0.05, # Example - may need tuning
        min_ar = 0.33, # Example - may need tuning
        snap_layer = -1, # Disable snapping if not explicitly requested and layer isn't found
        bus_planning_flag = False, # Disable bus planning
        report_directory = "" # No report directory
    )
else:
    print("INFO: No macros found in the design. Skipping macro placement.")

# Configure and run global placement
print(f"INFO: Running global placement with {global_placement_iterations} initial iterations.")
gpl = design.getReplace()
# Example settings - can be tuned
gpl.setTimingDrivenMode(False) # Set True for timing-driven placement
gpl.setRoutabilityDrivenMode(True)
gpl.setUniformTargetDensityMode(True)
# Set initial placement iterations as requested (interpreted from prompt)
gpl.setInitialPlaceMaxIter(global_placement_iterations)
gpl.setInitDensityPenalityFactor(0.05) # Example value
# Run initial and Nesterov global placement
gpl.doInitialPlace(threads = 4) # Use a reasonable number of threads
gpl.doNesterovPlace(threads = 4) # Use a reasonable number of threads
gpl.reset() # Reset the global placer state

# Run initial detailed placement
print("INFO: Running initial detailed placement.")
dp = design.getOpendp()
# Convert max displacement from microns to DBU
max_disp_x_dbu = design.micronToDBU(detailed_placement_max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(detailed_placement_max_disp_y_um)
# Detailed placement operates on site units, convert DBU to site units
# Need at least one row to get the site dimensions
rows = design.getBlock().getRows()
if not rows:
    print("ERROR: No rows found in the design. Cannot determine site dimensions for detailed placement.")
    exit(1)
site = rows[0].getSite()
if site.getWidth() == 0 or site.getHeight() == 0:
     print("ERROR: Site dimensions are zero. Cannot convert displacement to site units.")
     exit(1)

max_disp_x_site = int(max_disp_x_dbu / site.getWidth())
max_disp_y_site = int(max_disp_y_dbu / site.getHeight())

# Remove filler cells if any were inserted before detailed placement
# This is good practice if fillers were used in a previous stage
dp.removeFillers()
# Perform detailed placement
# detailedPlacement(max_displ_x, max_displ_y, filler_cell_prefix, incremental)
dp.detailedPlacement(max_disp_x_site, max_disp_y_site, "", False) # Use False for non-incremental

# Configure and run clock tree synthesis
print("INFO: Running clock tree synthesis.")
# Set RC values for clock and signal nets used in CTS tree building
design.evalTclString(f"set_wire_rc -clock -resistance {wire_rc_resistance} -capacitance {wire_rc_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {wire_rc_resistance} -capacitance {wire_rc_capacitance}") # Also set for signal nets as needed

cts = design.getTritonCts()
cts_parms = cts.getParms()
cts_parms.setWireSegmentUnit(20) # Example value - affects segment length in CTS tree
# Configure clock buffers
cts.setBufferList(cts_buffer_cell_name) # List of allowed clock buffer cells
cts.setRootBuffer(cts_buffer_cell_name) # Cell to use for the root buffer
# Sink buffer can be different, but using same as example/default
cts.setSinkBuffer(cts_buffer_cell_name)
# Run CTS
cts.runTritonCts()
# Set the clock signal as propagated again after CTS modifies the clock net structure
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Run final detailed placement after CTS to legalize cells inserted by CTS
print("INFO: Running post-CTS detailed placement.")
# Max displacement set to 0,0 as requested
dp.detailedPlacement(max_disp_x_site, max_disp_y_site, "", False) # Use False for non-incremental legalization

# Insert filler cells to fill gaps between standard cells after final placement
print("INFO: Inserting filler cells.")
filler_masters = list()
# Collect all CORE_SPACER masters from all libraries
# Example prefix - adjust if your library uses a different naming convention
filler_cells_prefix = "FILLCELL_"
for lib in db.getLibs():
    for master in lib.getMasters():
        # Master type can be CORE_SPACER, CORE, or other fill types
        if master.getType() in ("CORE_SPACER", "CORE"):
            # Check if the cell master name starts with the filler prefix or is a known filler
            # This is just an example check, library might have different naming
            if master.getName().startswith(filler_cells_prefix) or "FILLCELL" in master.getName().upper():
                 filler_masters.append(master)

# Insert fillers if found
if len(filler_masters) == 0:
    print("WARNING: No filler cells found (CORE_SPACER type or matching prefix). Skipping filler placement.")
else:
    # fillerPlacement(filler_masters, prefix, verbose)
    # The prefix argument here is used to name the created filler instances
    dp.fillerPlacement(filler_masters = filler_masters,
                       prefix = filler_cells_prefix,
                       verbose = False)

# Configure power delivery network
print("INFO: Configuring power delivery network.")
pdngen = design.getPdnGen()

# Set up global power/ground connections
# Mark power/ground nets as special nets (usually done after linking/global connect)
# This might be redundant if globalConnect handles it, but ensures nets are marked
for net in design.getBlock().getNets():
    if net.getSigType() == "POWER" or net.getSigType() == "GROUND":
        net.setSpecial()

# Find existing power and ground nets or create if needed
# Assuming standard VDD and VSS net names
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")
switched_power = None  # No switched power domain in this design
secondary = list()  # No secondary power nets

# Create VDD/VSS nets if they don't exist (handle cases where netlist doesn't have explicit VDD/VSS ports)
if VDD_net is None:
    VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
    VDD_net.setSpecial()
    VDD_net.setSigType("POWER")
    print("WARNING: VDD net not found, creating it.")
if VSS_net is None:
    VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
    VSS_net.setSpecial()
    VSS_net.setSigType("GROUND")
    print("WARNING: VSS net not found, creating it.")

# Connect standard cell and macro power pins to global nets using patterns
print("INFO: Applying global power/ground connections.")
# These patterns are common but may need adjustment based on library pin names
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDPE$", net = VDD_net, do_connect = True) # Example power pin
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDCE$", net = VDD_net, do_connect = True) # Example power pin
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSSE$", net = VSS_net, do_connect = True) # Example ground pin
# Apply the global connections
design.getBlock().globalConnect()

# Configure power domains - required even for a single domain
# Set core power domain with primary power/ground nets
pdngen.setCoreDomain(power = VDD_net, switched_power = switched_power, ground = VSS_net, secondary = secondary)
domains = [pdngen.findDomain("Core")] # Get the created domain

# Convert PDN dimensions and offsets from microns to DBU
pdn_via_cut_pitch_dbu = design.micronToDBU(pdn_via_cut_pitch_um)
pdn_offset_dbu = design.micronToDBU(pdn_offset_um)

# Get metal layers for power grid implementation using db object
m1 = db.getTech().findLayer("metal1")
m4 = db.getTech().findLayer("metal4")
m5 = db.getTech().findLayer("metal5")
m6 = db.getTech().findLayer("metal6")
m7 = db.getTech().findLayer("metal7")
m8 = db.getTech().findLayer("metal8")

# Check if required layers exist
required_pdn_layers = { "metal1":m1, "metal4":m4, "metal5":m5, "metal6":m6, "metal7":m7, "metal8":m8 }
for name, layer in required_pdn_layers.items():
    if layer is None:
        print(f"ERROR: Required PDN layer '{name}' not found in technology LEF.")
        exit(1)

# Get routing layers for power ring connections to pads (using all routing layers as in examples)
# This is often used for connecting the core grid rings to pad power/ground pins
ring_connect_to_pad_layers = list()
for layer in db.getTech().getLayers():
    if layer.getType() == "ROUTING":
        ring_connect_to_pad_layers.append(layer)
# Ensure the layers actually exist and have routing properties
ring_connect_to_pad_layers = [l for l in ring_connect_to_pad_layers if l.hasRouting() and l.getLevel() > 0]


# Create power grid for standard cells
print("INFO: Creating standard cell power grid.")
for domain in domains:
    # Create the main core grid structure for standard cells
    # starts_with determines the initial element pattern. Using RING aligns with M7/M8 rings first.
    pdngen.makeCoreGrid(domain = domain,
                        name = "std_cell_grid",
                        starts_with = pdn.RING, # Start pattern with rings (M7/M8)
                        pin_layers = [], # Pin layers not specified, leave empty
                        generate_obstructions = [], # Do not generate obstructions automatically
                        powercell = None, # No power cell definition
                        powercontrol = None, # No power control definition
                        powercontrolnetwork = "STAR") # Example network type (STAR, CHAIN, etc.)

# Get the created standard cell grid (findGrid returns a list)
std_cell_grid_list = pdngen.findGrid("std_cell_grid")
if std_cell_grid_list:
    std_cell_grid = std_cell_grid_list[0] # Assuming one core grid per domain

    # Add rings, straps, and connects to the standard cell grid
    g = std_cell_grid # Alias for clarity

    # Create power rings around core area using metal7 and metal8 (5um width/spacing)
    print(f"INFO: Adding standard cell rings on {m7.getName()} and {m8.getName()} (width/spacing 5 um).")
    pdngen.makeRing(grid = g,
                    layer0 = m7, # Lower layer of the ring pair
                    width0 = design.micronToDBU(std_cell_ring_m7_width_um),
                    spacing0 = design.micronToDBU(std_cell_ring_m7_spacing_um),
                    layer1 = m8, # Upper layer of the ring pair
                    width1 = design.micronToDBU(std_cell_ring_m8_width_um),
                    spacing1 = design.micronToDBU(std_cell_ring_m8_spacing_um),
                    starts_with = pdn.GRID, # Pattern starts relative to the grid definition (here, the core boundary)
                    offset = [pdn_offset_dbu for i in range(4)], # Offset 0 as requested
                    pad_offset = [pdn_offset_dbu for i in range(4)], # Offset 0 as requested relative to pads
                    extend = pdn.BOUNDARY, # Extend ring to the design boundary
                    pad_pin_layers = ring_connect_to_pad_layers, # Layers used to connect rings to pads
                    nets = []) # Use default nets from grid domain (VDD/VSS)

    # Create horizontal power straps on metal1 (followpin - follows standard cell rows)
    print(f"INFO: Adding standard cell M1 followpin straps (width {std_cell_strap_m1_width_um} um).")
    pdngen.makeFollowpin(grid = g,
                         layer = m1, # Layer for followpin straps
                         width = design.micronToDBU(std_cell_strap_m1_width_um),
                         extend = pdn.CORE) # Extend followpins within the core area

    # Create vertical power straps on metal4
    print(f"INFO: Adding standard cell M4 vertical straps (width {std_cell_strap_m4_width_um} um, spacing {std_cell_strap_m4_spacing_um} um, pitch {std_cell_strap_m4_pitch_um} um).")
    pdngen.makeStrap(grid = g,
                     layer = m4, # Layer for vertical straps
                     width = design.micronToDBU(std_cell_strap_m4_width_um),
                     spacing = design.micronToDBU(std_cell_strap_m4_spacing_um),
                     pitch = design.micronToDBU(std_cell_strap_m4_pitch_um),
                     offset = pdn_offset_dbu, # Offset 0 as requested
                     number_of_straps = 0, # Auto-calculate number of straps based on pitch/spacing
                     snap = False, # Do not snap strap start to a specific grid location
                     starts_with = pdn.GRID, # Start strap pattern relative to the grid definition
                     extend = pdn.CORE, # Extend straps within the core area
                     nets = []) # Use default nets from grid domain

    # Create vertical power straps on metal7
    print(f"INFO: Adding standard cell M7 vertical straps (width {std_cell_strap_m7_width_um} um, spacing {std_cell_strap_m7_spacing_um} um, pitch {std_cell_strap_m7_pitch_um} um).")
    pdngen.makeStrap(grid = g,
                     layer = m7, # Layer for vertical straps
                     width = design.micronToDBU(std_cell_strap_m7_width_um),
                     spacing = design.micronToDBU(std_cell_strap_m7_spacing_um),
                     pitch = design.micronToDBU(std_cell_strap_m7_pitch_um),
                     offset = pdn_offset_dbu, # Offset 0 as requested
                     number_of_straps = 0, # Auto-calculate
                     snap = False,
                     starts_with = pdn.GRID,
                     extend = pdn.RINGS, # Extend to connect to the standard cell rings
                     nets = [])

    # Create via connections between standard cell grid layers
    # The cut_pitch_x/y parameter controls the pitch of via arrays for connections
    print(f"INFO: Adding standard cell grid via connections (cut pitch {pdn_via_cut_pitch_um} um).")
    # Connect metal1 (followpins) to metal4 (vertical straps)
    pdngen.makeConnect(grid = g, layer0 = m1, layer1 = m4,
                       cut_pitch_x = pdn_via_cut_pitch_dbu, cut_pitch_y = pdn_via_cut_pitch_dbu)
    # Connect metal4 (vertical straps) to metal7 (vertical straps)
    pdngen.makeConnect(grid = g, layer0 = m4, layer1 = m7,
                       cut_pitch_x = pdn_via_cut_pitch_dbu, cut_pitch_y = pdn_via_cut_pitch_dbu)
    # Connect metal7 (vertical straps) to metal8 (rings)
    pdngen.makeConnect(grid = g, layer0 = m7, layer1 = m8,
                       cut_pitch_x = pdn_via_cut_pitch_dbu, cut_pitch_y = pdn_via_cut_pitch_dbu)
else:
    print("WARNING: Standard cell grid 'std_cell_grid' not found after makeCoreGrid.")


# Create power grid for macro blocks if macros exist
if len(macros) > 0:
    print("INFO: Creating macro power grids.")
    # Set halo around macros for macro grid definition (should match macro_halo_um)
    macro_grid_halo = [design.micronToDBU(macro_halo_um) for i in range(4)]

    for i, macro_inst in enumerate(macros):
        print(f"INFO: Creating power grid for macro instance '{macro_inst.getName()}'.")
        for domain in domains:
            # Create separate power grid structure for each macro instance
            pdngen.makeInstanceGrid(domain = domain,
                                    name = f"macro_grid_{macro_inst.getName()}", # Use instance name for unique grid name
                                    starts_with = pdn.RING, # Start pattern with rings (M5/M6)
                                    inst = macro_inst, # Associate grid with this instance
                                    halo = macro_grid_halo, # Halo around the macro instance within which the grid is defined
                                    pg_pins_to_boundary = True,  # Connect macro power/ground pins to grid boundary
                                    default_grid = False, # Not a default grid for the whole core
                                    generate_obstructions = [],
                                    is_bump = False) # Not a bump grid

        # Get the created macro grid (findGrid returns a list)
        macro_grid_list = pdngen.findGrid(f"macro_grid_{macro_inst.getName()}")
        if macro_grid_list:
          macro_grid = macro_grid_list[0] # Assuming one grid per instance/domain
          g_macro = macro_grid # Alias for clarity

          # Add rings, straps, and connects to the macro grid
          # Create power ring around macro using metal5 and metal6
          # Using dimensions from prompt for M5/M6 macro grids (1.2um width/spacing)
          print(f"INFO: Adding macro rings on {m5.getName()} and {m6.getName()} (width/spacing {macro_m5_width_um} um).")
          pdngen.makeRing(grid = g_macro,
                          layer0 = m5,
                          width0 = design.micronToDBU(macro_m5_width_um), # Use macro strap width/spacing
                          spacing0 = design.micronToDBU(macro_m5_spacing_um),
                          layer1 = m6,
                          width1 = design.micronToDBU(macro_m6_width_um), # Use macro strap width/spacing
                          spacing1 = design.micronToDBU(macro_m6_spacing_um),
                          starts_with = pdn.GRID, # Start ring pattern based on macro instance boundary
                          offset = [pdn_offset_dbu for i in range(4)], # Offset 0
                          pad_offset = [pdn_offset_dbu for i in range(4)], # Offset 0 (no pads for macro grids)
                          extend = pdn.BOUNDARY, # Extend to macro instance boundary
                          pad_pin_layers = [], # No pads for macro grids
                          nets = []) # Use default nets from grid

          # Create power straps on metal5 for macro connections
          print(f"INFO: Adding macro M5 straps (width {macro_m5_width_um} um, spacing {macro_m5_spacing_um} um, pitch {macro_m5_pitch_um} um).")
          pdngen.makeStrap(grid = g_macro,
                           layer = m5, # Layer for straps
                           width = design.micronToDBU(macro_m5_width_um),
                           spacing = design.micronToDBU(macro_m5_spacing_um),
                           pitch = design.micronToDBU(macro_m5_pitch_um),
                           offset = pdn_offset_dbu, # Offset 0
                           number_of_straps = 0,
                           snap = True, # Snap straps to grid (macro grid boundary)
                           starts_with = pdn.GRID,
                           extend = pdn.RINGS, # Extend to the macro rings
                           nets = [])

          # Create power straps on metal6 for macro connections
          print(f"INFO: Adding macro M6 straps (width {macro_m6_width_um} um, spacing {macro_m6_spacing_um} um, pitch {macro_m6_pitch_um} um).")
          pdngen.makeStrap(grid = g_macro,
                           layer = m6, # Layer for straps
                           width = design.micronToDBU(macro_m6_width_um),
                           spacing = design.micronToDBU(macro_m6_spacing_um),
                           pitch = design.micronToDBU(macro_m6_pitch_um),
                           offset = pdn_offset_dbu, # Offset 0
                           number_of_straps = 0,
                           snap = True,
                           starts_with = pdn.GRID,
                           extend = pdn.RINGS, # Extend to the macro rings
                           nets = [])

          # Create via connections between macro power grid layers and core grid layers
          # Connects the macro grid into the main standard cell grid structure
          print(f"INFO: Adding macro grid via connections (cut pitch {pdn_via_cut_pitch_um} um).")
          # Connect metal4 (from core grid) to metal5 (macro grid)
          pdngen.makeConnect(grid = g_macro, layer0 = m4, layer1 = m5,
                             cut_pitch_x = pdn_via_cut_pitch_dbu, cut_pitch_y = pdn_via_cut_pitch_dbu)
          # Connect metal5 to metal6 (within macro grid)
          pdngen.makeConnect(grid = g_macro, layer0 = m5, layer1 = m6,
                             cut_pitch_x = pdn_via_cut_pitch_dbu, cut_pitch_y = pdn_via_cut_pitch_dbu)
          # Connect metal6 (macro grid) to metal7 (core grid)
          pdngen.makeConnect(grid = g_macro, layer0 = m6, layer1 = m7,
                             cut_pitch_x = pdn_via_cut_pitch_dbu, cut_pitch_y = pdn_via_cut_pitch_dbu)
        else:
             print(f"WARNING: Macro grid 'macro_grid_{macro_inst.getName()}' not found after makeInstanceGrid.")

# Generate the final power delivery network geometry
print("INFO: Building and writing power grids.")
pdngen.checkSetup()  # Verify configuration
pdngen.buildGrids(False)  # Build the power grid geometry in memory
pdngen.writeToDb(True, )  # Write power grid shapes to the design database
pdngen.resetShapes()  # Reset temporary shapes generated during buildGrids

# Run static IR drop analysis on VDD net at instance pins
# This simulates the voltage seen by standard cell power pins connected to the grid.
# Placed after PDN generation and before routing as per prompt.
print(f"INFO: Running static IR drop analysis on net '{ir_drop_analysis_net_name}'.")
psm_obj = design.getPDNSim()
# Get the first timing corner (required for analysis context, like instance power data)
timing = Timing(design)
corners = timing.getCorners()
if not corners:
    print("WARNING: No timing corners defined. Skipping IR drop analysis.")
else:
    ir_drop_net = design.getBlock().findNet(ir_drop_analysis_net_name)
    if ir_drop_net is None:
        print(f"ERROR: Specified IR drop net '{ir_drop_analysis_net_name}' not found for analysis.")
    else:
        # Analyze voltage at instance pins connected to the specified net (VDD or VSS)
        # This requires power data (switching, leakage, internal) to be loaded or estimated.
        # Assumes default power data is available or previously loaded (e.g., from an activity file).
        psm_obj.analyzePowerGrid(net = ir_drop_net,
                                 enable_em = False, # Electromigration analysis disabled
                                 corner = corners[0], # Use the first timing corner
                                 use_prev_solution = False,
                                 em_file = "", # EM report file (if EM enabled)
                                 error_file = "", # Optional error output file
                                 voltage_source_file = "", # Optional voltage source file
                                 voltage_file = output_ir_report, # Output voltage/IR drop report file
                                 source_type = psm.SourceType_INST_PINS) # Analyze current sources at instance pins

        print(f"INFO: IR Drop analysis complete. Report saved to '{output_ir_report}'.")

# Report power (switching, internal, leakage, total)
# Placed after IR drop analysis and before routing as per prompt.
print("INFO: Reporting power consumption.")
# report_power command usually includes these categories if power data is available (e.g., from Liberty + activity file)
try:
    design.evalTclString(f"report_power > {output_power_report}")
    print(f"INFO: Power report saved to '{output_power_report}'.")
except Exception as e:
    print(f"WARNING: Failed to generate power report. Power data might not be available or command failed.")
    print(f"Error details: {e}")


# Configure and run global routing
print(f"INFO: Running global routing on layers {routing_bottom_layer_name} to {routing_top_layer_name}.")
grt = design.getGlobalRouter()

# Find routing layers by name and get their levels using db object
bottom_route_layer = db.getTech().findLayer(routing_bottom_layer_name)
top_route_layer = db.getTech().findLayer(routing_top_layer_name)

if bottom_route_layer is None:
    print(f"ERROR: Bottom routing layer '{routing_bottom_layer_name}' not found in technology LEF.")
    exit(1)
if top_route_layer is None:
    print(f"ERROR: Top routing layer '{routing_top_layer_layer_name}' not found in technology LEF.")
    exit(1)

signal_low_layer_level = bottom_route_layer.getRoutingLevel()
signal_high_layer_level = top_route_layer.getRoutingLevel()

# Set routing layer ranges for signal and clock nets
grt.setMinRoutingLayer(signal_low_layer_level)
grt.setMaxRoutingLayer(signal_high_layer_level)
grt.setMinLayerForClock(signal_low_layer_level) # Use same range for clock routing
grt.setMaxLayerForClock(signal_high_layer_level)

grt.setAdjustment(0.5) # Example congestion adjustment (0.0-1.0, higher means more space)
grt.setVerbose(True) # Enable verbose output
grt.globalRoute(True) # Run global routing (True might enable routing on blockage or other settings)

# Configure and run detailed routing
print(f"INFO: Running detailed routing on layers {routing_bottom_layer_name} to {routing_top_layer_name}.")
drter = design.getTritonRoute()
dr_params = drt.ParamStruct()
# Set detailed routing layer range
dr_params.bottomRoutingLayer = routing_bottom_layer_name
dr_params.topRoutingLayer = routing_top_layer_name
dr_params.enableViaGen = True # Enable via generation
dr_params.drouteEndIter = 1 # Run 1 detailed routing iteration (can increase for better results/DRC reduction)
dr_params.verbose = 1 # Verbose output level (0=quiet, 1=normal, 2=debug)
dr_params.cleanPatches = True # Clean up patches after routing
dr_params.doPa = True # Perform post-route antenna fixing (if enabled in build and libraries)
# Other parameters can be left as defaults or tuned if needed for specific technologies or issues
# dr_params.outputMazeFile = "" # Optional debug file
# dr_params.outputDrcFile = "" # Optional DRC output file
# dr_params.outputCmapFile = ""
# dr_params.outputGuideCoverageFile = ""
# dr_params.dbProcessNode = "" # Example: "14nm" for specific technology nodes
# dr_params.viaInPinBottomLayer = "" # Specify if via-in-pin is allowed/required on specific layers
# dr_params.viaInPinTopLayer = ""
# dr_params.orSeed = -1 # Use random seed for routing
# dr_params.orK = 0 # Maze routing parameter

drter.setParams(dr_params)
drter.main() # Run detailed routing

# Final DEF dump at the end of the flow as requested
print(f"INFO: Dumping final DEF file to {output_def_file}.")
design.writeDef(output_def_file)

print(f"INFO: Design flow complete. Final DEF saved to {output_def_file}")