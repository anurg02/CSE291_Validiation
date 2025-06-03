# OpenROAD Python script for gate-level physical design flow

# This script performs a typical gate-level physical design flow using OpenROAD,
# including reading inputs, clock definition, floorplan, placement (macros and
# standard cells), power delivery network (PDN) generation, clock tree synthesis (CTS),
# filler cell insertion, routing, power analysis, and output generation.

# Based on the provided prompt and consolidating best practices.

# Import necessary OpenROAD modules
from openroad import Tech, Design, Timing
import odb
import pdn
import drt
import openroad as ord # Use ord as a common alias for the top-level module
import psm
from pathlib import Path
import sys

# --- Configuration ---
# !! IMPORTANT: Replace these paths with the actual paths for your design !!
# You might need to adjust these paths based on your specific project structure
DESIGN_DIR = Path("/path/to/your/verilog")       # e.g., Path("./results/synthesis")
LIB_DIR = Path("/path/to/your/lib")             # e.g., Path("./tech/mylib/lib")
LEF_DIR = Path("/path/to/your/lef")             # e.g., Path("./tech/mylib/lef")

# Input Files
VERILOG_FILE = DESIGN_DIR / "input_netlist.v"    # !! Replace with the actual netlist file name !!

# Design Parameters
TOP_MODULE_NAME = "your_top_module_name"         # !! Replace with the actual top module name !!
CLOCK_PORT_NAME = "clk"                          # Clock input port name
CLOCK_NET_NAME = "core_clock"                    # Name to assign to the clock net for timing
CLOCK_PERIOD_NS = 50.0                           # Clock period in nanoseconds

# Standard Cell RC values (per unit length)
WIRE_RESISTANCE_PER_UNIT = 0.03574               # Resistance (ohms/DBU)
WIRE_CAPACITANCE_PER_UNIT = 0.07516              # Capacitance (F/DBU)

# Floorplan Parameters (in microns)
DIE_AREA_BL_X_UM = 0.0
DIE_AREA_BL_Y_UM = 0.0
DIE_AREA_TR_X_UM = 45.0
DIE_AREA_TR_Y_UM = 45.0

CORE_AREA_BL_X_UM = 5.0
CORE_AREA_BL_Y_UM = 5.0
CORE_AREA_TR_X_UM = 40.0
CORE_AREA_TR_Y_UM = 40.0

SITE_NAME = "core"                               # !! Replace with actual standard cell site name from LEF !!

# Placement Parameters (in microns)
MACRO_FENCE_BL_X_UM = 5.0
MACRO_FENCE_BL_Y_UM = 5.0
MACRO_FENCE_TR_X_UM = 20.0
MACRO_FENCE_TR_Y_UM = 25.0
MACRO_HALO_WIDTH_UM = 5.0                        # Halo around macros (affects min spacing)
MACRO_HALO_HEIGHT_UM = 5.0

GLOBAL_PLACEMENT_ITERATIONS = 20                 # Initial placement iterations for RePlAce

DETAILED_PLACEMENT_MAX_DISP_X_UM = 0.5           # Max displacement for OpenDP in X
DETAILED_PLACEMENT_MAX_DISP_Y_UM = 0.5           # Max displacement for OpenDP in Y

# Power Delivery Network (PDN) Parameters (in microns)
PDN_CUT_PITCH_X_UM = 0.0                         # Via cut pitch between grids (0 for dense)
PDN_CUT_PITCH_Y_UM = 0.0

# Core Grid Straps/Rings
M1_STRAP_WIDTH_UM = 0.07                         # Standard cell followpin width on M1
M4_STRAP_WIDTH_UM = 1.2
M4_STRAP_SPACING_UM = 1.2
M4_STRAP_PITCH_UM = 6.0
M7_STRAP_WIDTH_UM = 1.4
M7_STRAP_SPACING_UM = 1.4
M7_STRAP_PITCH_UM = 10.8
M8_STRAP_WIDTH_UM = 1.4                          # Assuming same width/spacing as M7 straps for simplicity
M8_STRAP_SPACING_UM = 1.4
M8_STRAP_PITCH_UM = 10.8
CORE_RING_WIDTH_UM = 4.0
CORE_RING_SPACING_UM = 4.0
PDN_OFFSET_UM = 0.0                              # Offset for all PDN features

# Macro Grid Straps (if macros exist and M5/M6 used)
MACRO_M5_M6_STRAP_WIDTH_UM = 1.2
MACRO_M5_M6_STRAP_SPACING_UM = 1.2
MACRO_M5_M6_STRAP_PITCH_UM = 6.0

# PDN Layers - map logical names to actual layer objects later
PDN_LAYERS = {
    "M1": "metal1",
    "M4": "metal4",
    "M5": "metal5", # For macro grid
    "M6": "metal6", # For macro grid
    "M7": "metal7",
    "M8": "metal8",
}

# Clock Tree Synthesis (CTS) Parameters
CTS_BUFFER_CELL_NAME = "BUF_X2"                  # !! Replace with actual buffer cell name from library !!
CTS_WIRE_SEGMENT_UNIT = 20                       # CTS wire segment unit length (DBU)

# Filler Cell Parameters
FILLER_CELL_PREFIX = "FILLCELL_"                 # !! Verify this prefix matches library filler cell names !!

# Routing Parameters
GLOBAL_ROUTING_MIN_LAYER = "metal1"              # Min layer for global routing
GLOBAL_ROUTING_MAX_LAYER = "metal7"              # Max layer for global routing
DETAILED_ROUTING_MIN_LAYER = "metal1"            # Min layer for detailed routing
DETAILED_ROUTING_MAX_LAYER = "metal7"            # Max layer for detailed routing

# Output Files
FINAL_DEF_FILE = "final.def"
FINAL_ODB_FILE = "final.odb"
POWER_REPORT_FILE = "power_report.txt"

# --- Initialization and Input Reading ---
print("--- Initializing OpenROAD ---")
# Initialize OpenROAD technology and design objects
tech = Tech()
design = Design(tech)

db = ord.get_db() # Get the database object

# Helper function to read files and handle errors
def read_files(directory, pattern, read_func, file_type):
    print(f"Reading {file_type} files from {directory}...")
    files = list(directory.glob(pattern))
    if not files:
        print(f"Warning: No {file_type} files found in {directory} matching pattern '{pattern}'.")
        # Allow script to continue, but subsequent steps might fail
    for file in files:
        try:
            read_func(file.as_posix())
            print(f"Successfully read: {file.name}")
        except Exception as e:
            print(f"Error reading {file_type} file {file.name}: {e}")
            # Decide whether to exit or continue on error
            # sys.exit(1) # Uncomment to exit on first file read error

# Read all library (.lib) files
read_files(LIB_DIR, "*.lib", tech.readLiberty, "liberty")

# Read tech LEF files
read_files(LEF_DIR, "*.tech.lef", tech.readLef, "tech LEF")

# Read cell LEF files
read_files(LEF_DIR, "*.lef", tech.readLef, "cell LEF")

# Create design and read Verilog netlist
print(f"Reading Verilog netlist: {VERILOG_FILE}...")
if not VERILOG_FILE.exists():
    print(f"Error: Verilog file not found: {VERILOG_FILE}")
    sys.exit(1)
design.readVerilog(VERILOG_FILE.as_posix())
print("Verilog netlist read.")

# Link the design to the libraries
print(f"Linking design: {TOP_MODULE_NAME}...")
design.link(TOP_MODULE_NAME)

# Check if linking was successful
if design.getBlock() is None:
    print(f"Error: Failed to link design '{TOP_MODULE_NAME}'. Ensure the top module name matches the Verilog and it exists in the libraries.")
    sys.exit(1)
print("Design linked successfully.")

# --- Clock Definition ---
print("\n--- Defining Clock ---")
# Define clock period in nanoseconds
# Define the clock port name and clock net name

# Check if the clock port exists
clock_port = design.getBlock().findBTerm(CLOCK_PORT_NAME)
if clock_port is None:
    print(f"Error: Clock port '{CLOCK_PORT_NAME}' not found in the design. Timing setup and CTS will fail.")
    # Continue script, but note the critical missing clock port
else:
    # Create clock signal on the specified port using Tcl command for robustness
    print(f"Creating clock '{CLOCK_NET_NAME}' with period {CLOCK_PERIOD_NS}ns on port '{CLOCK_PORT_NAME}'")
    design.evalTclString(f"create_clock -period {CLOCK_PERIOD_NS} [get_ports {CLOCK_PORT_NAME}] -name {CLOCK_NET_NAME}")
    # Propagate the clock signal (required for static timing analysis)
    print(f"Setting propagated clock for '{CLOCK_NET_NAME}'")
    design.evalTclString(f"set_propagated_clock [get_clocks {{{CLOCK_NET_NAME}}}]")

    # Set RC values for clock and signal nets
    # Note: The prompt asks for unit resistance/capacitance. set_wire_rc uses
    # resistance/capacitance per DBU or per micron depending on tool version/units.
    # Assuming the provided values are per DBU or compatible units used by set_wire_rc.
    print(f"Setting clock wire RC: R={WIRE_RESISTANCE_PER_UNIT}, C={WIRE_CAPACITANCE_PER_UNIT}")
    design.evalTclString(f"set_wire_rc -clock -resistance {WIRE_RESISTANCE_PER_UNIT} -capacitance {WIRE_CAPACITANCE_PER_UNIT}")
    print(f"Setting signal wire RC: R={WIRE_RESISTANCE_PER_UNIT}, C={WIRE_CAPACITANCE_PER_UNIT}")
    design.evalTclString(f"set_wire_rc -signal -resistance {WIRE_RESISTANCE_PER_UNIT} -capacitance {WIRE_CAPACITANCE_PER_UNIT}")

# --- Floorplanning ---
print("\n--- Performing Floorplanning ---")
# Initialize floorplan object
floorplan = design.getFloorplan()
block = design.getBlock()

# Set die area in DBU
die_area = odb.Rect(design.micronToDBU(DIE_AREA_BL_X_UM), design.micronToDBU(DIE_AREA_BL_Y_UM),
                    design.micronToDBU(DIE_AREA_TR_X_UM), design.micronToDBU(DIE_AREA_TR_Y_UM))
print(f"Set die area: ({DIE_AREA_BL_X_UM}um, {DIE_AREA_BL_Y_UM}um) to ({DIE_AREA_TR_X_UM}um, {DIE_AREA_TR_Y_UM}um)")

# Set core area in DBU
core_area = odb.Rect(design.micronToDBU(CORE_AREA_BL_X_UM), design.micronToDBU(CORE_AREA_BL_Y_UM),
                     design.micronToDBU(CORE_AREA_TR_X_UM), design.micronToDBU(CORE_AREA_TR_Y_UM))
print(f"Set core area: ({CORE_AREA_BL_X_UM}um, {CORE_AREA_BL_Y_UM}um) to ({CORE_AREA_TR_X_UM}um, {CORE_AREA_TR_Y_UM}um)")

# Find a site from the technology library
site = floorplan.findSite(SITE_NAME)
if site is None:
    print(f"Error: Could not find site '{SITE_NAME}'. Please check your LEF files for valid site names.")
    sys.exit(1)
print(f"Found standard cell site: {site.getName()}")

# Initialize floorplan with die and core areas, and the site
floorplan.initFloorplan(die_area, core_area, site)
# Create placement rows/tracks based on the floorplan
floorplan.makeTracks()
print("Floorplan initialized and tracks created.")

# --- Placement ---
print("\n--- Performing Placement ---")
# Identify macro blocks
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

# Configure and run macro placement if macros exist
if macros:
    print(f"Found {len(macros)} macros. Performing macro placement...")
    mpl = design.getMacroPlacer()

    # Set fence region for macros in microns
    print(f"Set macro fence region: ({MACRO_FENCE_BL_X_UM}um, {MACRO_FENCE_BL_Y_UM}um) to ({MACRO_FENCE_TR_X_UM}um, {MACRO_FENCE_TR_Y_UM}um)")

    # Set halo around each macro in microns (ensures minimum spacing)
    # A halo of 5um means instances will not be placed within 5um of the macro boundary.
    # Two macros with 5um halos will be at least 10um apart edge-to-edge.
    # If the prompt means minimum edge-to-edge spacing of 5um, the halo should be 2.5um.
    # Using 5um halo as written, interpreting "5 um to each other" generously.
    print(f"Set macro halo: {MACRO_HALO_WIDTH_UM}um width, {MACRO_HALO_HEIGHT_UM}um height")

    # Find a snapping layer (e.g., metal4 for macro pins)
    snap_layer_name = "metal4" # Example layer for pin snapping
    snap_layer = design.getTech().getDB().getTech().findLayer(snap_layer_name)
    snap_layer_level = 0
    if snap_layer:
        snap_layer_level = snap_layer.getRoutingLevel()
        print(f"Snapping macro pins to tracks on layer {snap_layer_name} (level {snap_layer_level})")
    else:
         print(f"Warning: {snap_layer_name} layer not found for macro pin snapping. Skipping pin snapping.")

    # Run macro placement
    # Note: mpl.place takes fence/halo values in microns directly
    mpl.place(
        num_threads = design.getThreadCount(), # Use configured thread count
        max_num_macro = len(macros),
        max_num_inst = 0, # Do not place standard cells with macro placer
        halo_width = MACRO_HALO_WIDTH_UM,
        halo_height = MACRO_HALO_HEIGHT_UM,
        fence_lx = MACRO_FENCE_BL_X_UM,
        fence_ly = MACRO_FENCE_BL_Y_UM,
        fence_ux = MACRO_FENCE_TR_X_UM,
        fence_uy = MACRO_FENCE_TR_Y_UM,
        snap_layer = snap_layer_level,
        # Other parameters can be tuned for quality (area_weight, wirelength_weight, etc.)
        # Using reasonable defaults or values derived from examples
        tolerance = 0.1,
        target_util = 0.50, # Example target utilization
        target_dead_space = 0.05,
        min_ar = 0.33,
        area_weight = 0.1,
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        pin_access_th = 0.1 # Example pin access threshold
    )
    print("Macro placement completed.")
else:
    print("No macros found in the design. Skipping macro placement.")

print("Performing global placement (standard cells)...")
# Configure and run global placement for standard cells using RePlAce
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # As per common basic flow examples, disable timing driven
gpl.setRoutabilityDrivenMode(True) # Enable routability driving
gpl.setUniformTargetDensityMode(True) # Use uniform density target
gpl.setInitialPlaceMaxIter(GLOBAL_PLACEMENT_ITERATIONS) # Set initial iterations
print(f"Set global placement initial iterations: {GLOBAL_PLACEMENT_ITERATIONS}")

# Run initial placement followed by Nesterov placement
# Using configured thread count
threads = design.getThreadCount() if design.getThreadCount() > 0 else 4 # Use 4 threads if no config
print(f"Running global placement with {threads} threads...")
gpl.doInitialPlace(threads=threads)
gpl.doNesterovPlace(threads=threads)

# Reset the placer state
gpl.reset()
print("Global placement completed.")

print("Performing initial detailed placement...")
# Configure and run detailed placement using OpenDP
opendp = design.getOpendp()

# Convert max displacement from microns to DBU
max_disp_x_dbu = design.micronToDBU(DETAILED_PLACEMENT_MAX_DISP_X_UM)
max_disp_y_dbu = design.micronToDBU(DETAILED_PLACEMENT_MAX_DISP_Y_UM)
print(f"Set detailed placement max displacement: {DETAILED_PLACEMENT_MAX_DISP_X_UM}um (X), {DETAILED_PLACEMENT_MAX_DISP_Y_UM}um (Y)")

# Detailed placement
# opendp.removeFillers() # No fillers inserted yet
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False) # "" for region, False for timing-driven
print("Initial detailed placement completed.")

# --- Power Delivery Network (PDN) ---
print("\n--- Constructing Power Delivery Network (PDN) ---")
pdngen = design.getPdnGen()

# Set up global power/ground connections
print("Adding global power/ground connections...")
# Identify and mark POWER/GROUND nets as special
for net in block.getNets():
    if net.getSigType() in ("POWER", "GROUND"):
        net.setSpecial()

# Find existing power and ground nets or create them
VDD_net = block.findNet("VDD") # Assuming VDD is the power net name
VSS_net = block.findNet("VSS") # Assuming VSS is the ground net name

if VDD_net is None:
    print("VDD net not found. Creating 'VDD' net.")
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSpecial()
    VDD_net.setSigType("POWER")
if VSS_net is None:
    print("VSS net not found. Creating 'VSS' net.")
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSpecial()
    VSS_net.setSigType("GROUND")

# Connect standard cell power pins to global power nets
# Assumes power pins are named VDD and VSS - adjust pattern if needed
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VDD$", net=VDD_net, do_connect=True)
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VSS$", net=VSS_net, do_connect=True)
block.globalConnect()
print("Global power/ground connections added.")

# Set the core voltage domain
# No switched power or secondary nets specified in prompt
core_domain = pdngen.setCoreDomain(power=VDD_net, ground=VSS_net)
if core_domain is None:
    print("Error: Failed to set core power domain.")
    # Continue, but PDN generation will likely fail
else:
    print("Core power domain set.")

# Convert global PDN offset to DBU
pdn_offset_dbu = design.micronToDBU(PDN_OFFSET_UM)
# Convert via cut pitch for parallel grids to DBU (requested 0 um)
cut_pitch_x_dbu = design.micronToDBU(PDN_CUT_PITCH_X_UM)
cut_pitch_y_dbu = design.micronToDBU(PDN_CUT_PITCH_Y_UM)
print(f"Set via cut pitch for parallel grids: {PDN_CUT_PITCH_X_UM}um (X), {PDN_CUT_PITCH_Y_UM}um (Y)")

# Get metal layer objects for PDN implementation
metal_layers = {}
tech_db = design.getTech().getDB().getTech()
for name, layer_name in PDN_LAYERS.items():
    layer_obj = tech_db.findLayer(layer_name)
    if layer_obj:
        metal_layers[name] = layer_obj
    else:
        print(f"Error: Metal layer '{layer_name}' ({name}) not found in technology LEF.")
        metal_layers[name] = None # Store None if not found

# Check for critical missing layers
required_layers = ["M1", "M4", "M7", "M8"]
missing_critical_layers = [name for name in required_layers if metal_layers.get(name) is None]
if missing_critical_layers:
    print(f"Error: Missing critical metal layers for core PDN: {', '.join([PDN_LAYERS.get(n, n) for n in missing_critical_layers])}. Aborting PDN generation.")
    core_domain = None # Invalidate domain to prevent proceeding

if core_domain:
    # Create the main core grid structure
    core_grid_name = "core_grid"
    print(f"Creating core grid '{core_grid_name}'...")
    pdngen.makeCoreGrid(domain=core_domain,
                        name=core_grid_name,
                        starts_with=pdn.GROUND, # Start with ground net (arbitrary choice)
                        powercell=None, # No specific power cell
                        powercontrol=None)

    core_grid = pdngen.findGrid(core_grid_name)
    if core_grid is None:
        print(f"Error: Could not find or create core grid '{core_grid_name}'.")
        core_domain = None # Prevent strap/ring creation

if core_domain:
    # Configure straps and rings for the core grid
    print("Adding core grid straps and rings...")
    # Assuming makeCoreGrid created a single grid object; iterate just in case
    for g in [core_grid]: # Wrap in list if only one grid expected
        # Create horizontal power straps on metal1 following standard cell power pins
        if metal_layers["M1"]:
            m1_strap_width_dbu = design.micronToDBU(M1_STRAP_WIDTH_UM)
            pdngen.makeFollowpin(grid=g, layer=metal_layers["M1"], width=m1_strap_width_dbu, extend=pdn.CORE, offset=pdn_offset_dbu)
            print(f"Added M1 followpin strap with width {M1_STRAP_WIDTH_UM}um")

        # Create power straps on metal4 (standard cell routing)
        if metal_layers["M4"]:
            m4_strap_width_dbu = design.micronToDBU(M4_STRAP_WIDTH_UM)
            m4_strap_spacing_dbu = design.micronToDBU(M4_STRAP_SPACING_UM)
            m4_strap_pitch_dbu = design.micronToDBU(M4_STRAP_PITCH_UM)
            pdngen.makeStrap(grid=g, layer=metal_layers["M4"], width=m4_strap_width_dbu,
                             spacing=m4_strap_spacing_dbu, pitch=m4_strap_pitch_dbu,
                             offset=pdn_offset_dbu, extend=pdn.CORE, starts_with=pdn.GRID)
            print(f"Added M4 strap with width {M4_STRAP_WIDTH_UM}um, spacing {M4_STRAP_SPACING_UM}um, pitch {M4_STRAP_PITCH_UM}um")

        # Create power straps on metal7 (higher level routing)
        if metal_layers["M7"]:
            m7_strap_width_dbu = design.micronToDBU(M7_STRAP_WIDTH_UM)
            m7_strap_spacing_dbu = design.micronToDBU(M7_STRAP_SPACING_UM)
            m7_strap_pitch_dbu = design.micronToDBU(M7_STRAP_PITCH_UM)
            pdngen.makeStrap(grid=g, layer=metal_layers["M7"], width=m7_strap_width_dbu,
                             spacing=m7_strap_spacing_dbu, pitch=m7_strap_pitch_dbu,
                             offset=pdn_offset_dbu, extend=pdn.RINGS, starts_with=pdn.GRID) # Extend to rings
            print(f"Added M7 strap with width {M7_STRAP_WIDTH_UM}um, spacing {M7_STRAP_SPACING_UM}um, pitch {M7_STRAP_PITCH_UM}um (extend to RINGS)")

        # Create power straps on metal8 (higher level routing)
        if metal_layers["M8"]:
            m8_strap_width_dbu = design.micronToDBU(M8_STRAP_WIDTH_UM)
            m8_strap_spacing_dbu = design.micronToDBU(M8_STRAP_SPACING_UM)
            m8_strap_pitch_dbu = design.micronToDBU(M8_STRAP_PITCH_UM)
            pdngen.makeStrap(grid=g, layer=metal_layers["M8"], width=m8_strap_width_dbu,
                             spacing=m8_strap_spacing_dbu, pitch=m8_strap_pitch_dbu,
                             offset=pdn_offset_dbu, extend=pdn.BOUNDARY, starts_with=pdn.GRID) # Extend to die boundary
            print(f"Added M8 strap with width {M8_STRAP_WIDTH_UM}um, spacing {M8_STRAP_SPACING_UM}um, pitch {M8_STRAP_PITCH_UM}um (extend to BOUNDARY)")

        # Create power rings around the core area using metal7 (horizontal) and metal8 (vertical)
        if metal_layers["M7"] and metal_layers["M8"]:
            core_ring_width_dbu = design.micronToDBU(CORE_RING_WIDTH_UM)
            core_ring_spacing_dbu = design.micronToDBU(CORE_RING_SPACING_UM)
            # Ring offset is relative to the core boundary by default for pdn.CORE_RING extend
            # Setting offset to 0,0,0,0 relative to core area boundary corners
            core_ring_core_offset_dbu = [pdn_offset_dbu, pdn_offset_dbu, pdn_offset_dbu, pdn_offset_dbu] # [left, bottom, right, top]
            pdngen.makeRing(grid=g,
                            layer0=metal_layers["M7"], width0=core_ring_width_dbu, spacing0=core_ring_spacing_dbu,
                            layer1=metal_layers["M8"], width1=core_ring_width_dbu, spacing1=core_ring_spacing_dbu,
                            offset=core_ring_core_offset_dbu,
                            extend=pdn.CORE_RING, # Explicitly extend relative to core boundary
                            starts_with=pdn.GRID)
            print(f"Added M7/M8 core rings with width {CORE_RING_WIDTH_UM}um and spacing {CORE_RING_SPACING_UM}um")

        # Create via connections between core power grid layers
        # Use requested 0um cut pitch for "parallel grids"
        if metal_layers["M1"] and metal_layers["M4"]:
            pdngen.makeConnect(grid=g, layer0=metal_layers["M1"], layer1=metal_layers["M4"], cut_pitch_x=cut_pitch_x_dbu, cut_pitch_y=cut_pitch_y_dbu)
            print(f"Added M1-M4 vias with 0um cut pitch")

        if metal_layers["M4"] and metal_layers["M7"]:
            pdngen.makeConnect(grid=g, layer0=metal_layers["M4"], layer1=metal_layers["M7"], cut_pitch_x=cut_pitch_x_dbu, cut_pitch_y=cut_pitch_y_dbu)
            print(f"Added M4-M7 vias with 0um cut pitch")

        if metal_layers["M7"] and metal_layers["M8"]:
            pdngen.makeConnect(grid=g, layer0=metal_layers["M7"], layer1=metal_layers["M8"], cut_pitch_x=cut_pitch_x_dbu, cut_pitch_y=cut_pitch_y_dbu)
            print(f"Added M7-M8 vias with 0um cut pitch")

# Create power grid for macro blocks if macros exist and layers M5/M6 are available
missing_macro_layers = [name for name in ["M5", "M6"] if metal_layers.get(name) is None]
if macros and not missing_macro_layers:
    print(f"Adding macro grid straps on M5 and M6...")
    m5_m6_strap_width_dbu = design.micronToDBU(MACRO_M5_M6_STRAP_WIDTH_UM)
    m5_m6_strap_spacing_dbu = design.micronToDBU(MACRO_M5_M6_STRAP_SPACING_UM)
    m5_m6_strap_pitch_dbu = design.micronToDBU(MACRO_M5_M6_STRAP_PITCH_UM)
    pdn_macro_halo_dbu = [design.micronToDBU(MACRO_HALO_WIDTH_UM), design.micronToDBU(MACRO_HALO_HEIGHT_UM), design.micronToDBU(MACRO_HALO_WIDTH_UM), design.micronToDBU(MACRO_HALO_HEIGHT_UM)] # [left, bottom, right, top]

    for i, macro_inst in enumerate(macros):
        # Create separate instance grid for each macro
        macro_grid_name = f"macro_grid_{macro_inst.getName()}"
        print(f"Creating instance grid '{macro_grid_name}' for {macro_inst.getName()}...")
        pdngen.makeInstanceGrid(domain=core_domain, # Apply to the Core domain
                                name=macro_grid_name,
                                inst=macro_inst,
                                halo=pdn_macro_halo_dbu,
                                pg_pins_to_boundary=True,
                                starts_with=pdn.GROUND)

        macro_grid = pdngen.findGrid(macro_grid_name)
        if macro_grid is None:
             print(f"Error: Could not find or create macro instance grid '{macro_grid_name}'. Skipping macro PDN for this instance.")
             continue

        for g in [macro_grid]:
            # Create power straps on metal5 for macro connections
            if metal_layers["M5"]:
                 pdngen.makeStrap(grid=g, layer=metal_layers["M5"], width=m5_m6_strap_width_dbu,
                                  spacing=m5_m6_strap_spacing_dbu, pitch=m5_m6_strap_pitch_dbu,
                                  offset=pdn_offset_dbu, extend=pdn.CORE, starts_with=pdn.GRID, snap=True)
                 print(f"Added M5 strap for {macro_inst.getName()} with width {MACRO_M5_M6_STRAP_WIDTH_UM}um, spacing {MACRO_M5_M6_STRAP_SPACING_UM}um, pitch {MACRO_M5_M6_STRAP_PITCH_UM}um")

            # Create power straps on metal6 for macro connections
            if metal_layers["M6"]:
                 pdngen.makeStrap(grid=g, layer=metal_layers["M6"], width=m5_m6_strap_width_dbu,
                                  spacing=m5_m6_strap_spacing_dbu, pitch=m5_m6_strap_pitch_dbu,
                                  offset=pdn_offset_dbu, extend=pdn.CORE, starts_with=pdn.GRID, snap=True)
                 print(f"Added M6 strap for {macro_inst.getName()} with width {MACRO_M5_M6_STRAP_WIDTH_UM}um, spacing {MACRO_M5_M6_STRAP_SPACING_UM}um, pitch {MACRO_M5_M6_STRAP_PITCH_UM}um")

            # Create via connections
            if metal_layers["M4"] and metal_layers["M5"]: # Connect macro grid to core grid layer M4
                 pdngen.makeConnect(grid=g, layer0=metal_layers["M4"], layer1=metal_layers["M5"], cut_pitch_x=cut_pitch_x_dbu, cut_pitch_y=cut_pitch_y_dbu)
                 print(f"Added M4-M5 vias for {macro_inst.getName()} with 0um cut pitch")

            if metal_layers["M5"] and metal_layers["M6"]:
                 pdngen.makeConnect(grid=g, layer0=metal_layers["M5"], layer1=metal_layers["M6"], cut_pitch_x=cut_pitch_x_dbu, cut_pitch_y=cut_pitch_y_dbu)
                 print(f"Added M5-M6 vias for {macro_inst.getName()} with 0um cut pitch")

            if metal_layers["M6"] and metal_layers["M7"]: # Connect macro grid to core grid layer M7
                 pdngen.makeConnect(grid=g, layer0=metal_layers["M6"], layer1=metal_layers["M7"], cut_pitch_x=cut_pitch_x_dbu, cut_pitch_y=cut_pitch_y_dbu)
                 print(f"Added M6-M7 vias for {macro_inst.getName()} with 0um cut pitch")
elif macros and missing_macro_layers:
     print(f"Skipping macro PDN creation: Macros found but missing required layers {', '.join([PDN_LAYERS.get(n, n) for n in missing_macro_layers])}.")
else:
    print("No macros found. Skipping macro PDN creation.")


# Generate the final power delivery network shapes
if core_domain:
    pdngen.checkSetup() # Verify PDN configuration
    print("Building power grid shapes...")
    pdngen.buildGrids(False) # Build all grids (False includes instance grids)
    print("Writing power grid shapes to database...")
    pdngen.writeToDb(True) # Write shapes to the design database
    pdngen.resetShapes() # Reset temporary shapes
    print("PDN construction completed.")
else:
    print("Skipping PDN build due to previous errors.")


# --- Clock Tree Synthesis (CTS) ---
print("\n--- Performing Clock Tree Synthesis (CTS) ---")
if clock_port is None:
    print("Skipping CTS: Clock port not found.")
else:
    cts = design.getTritonCts()
    parms = cts.getParms()

    # Set CTS parameters
    parms.setWireSegmentUnit(CTS_WIRE_SEGMENT_UNIT) # Set wire segment unit length in DBU
    print(f"Set CTS wire segment unit: {CTS_WIRE_SEGMENT_UNIT} DBU")

    # Configure clock buffers
    print(f"Setting CTS buffers to: {CTS_BUFFER_CELL_NAME}")
    cts.setBufferList(CTS_BUFFER_CELL_NAME)
    cts.setRootBuffer(CTS_BUFFER_CELL_NAME)
    cts.setSinkBuffer(CTS_BUFFER_CELL_NAME)

    # Set the clock nets for CTS
    # Need the dbNet object for the clock net
    clock_net_obj = block.findNet(CLOCK_NET_NAME)
    if clock_net_obj is None:
         print(f"Error: Clock net '{CLOCK_NET_NAME}' not found. Cannot perform CTS.")
    else:
        print(f"Setting CTS target clock net: {CLOCK_NET_NAME}")
        cts.setClockNets([clock_net_obj]) # Pass a list of dbNet objects

        # Run CTS
        print("Running TritonCTS...")
        cts.runTritonCts()
        print("CTS completed.")

print("Performing final detailed placement after CTS...")
# Run final detailed placement after CTS (standard practice)
# Use the same maximum displacement as before CTS
# Max displacement in DBU is already calculated: max_disp_x_dbu, max_disp_y_dbu

# Ensure OpenDP object is available
opendp = design.getOpendp()

# Detailed placement after CTS
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Final detailed placement completed.")

# --- Filler Cell Insertion ---
print("\n--- Inserting Filler Cells ---")
# Find filler cell masters in the library
filler_masters = []
for lib in db.getLibs():
    for master in lib.getMasters():
        # Filler cells typically have CORE_SPACER type
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

# Insert filler cells if found
if not filler_masters:
    print("No filler cells found with type CORE_SPACER. Skipping filler placement.")
else:
    print(f"Found {len(filler_masters)} filler cell masters. Inserting fillers with prefix '{FILLER_CELL_PREFIX}'...")
    # Ensure OpenDP object is available
    opendp = design.getOpendp()
    opendp.fillerPlacement(filler_masters=filler_masters,
                           prefix=FILLER_CELL_PREFIX,
                           verbose=False) # Set verbose to True for detailed output
    print("Filler cell insertion completed.")


# --- Routing ---
print("\n--- Performing Routing ---")
# Get routing layer objects
min_groute_layer = tech_db.findLayer(GLOBAL_ROUTING_MIN_LAYER)
max_groute_layer = tech_db.findLayer(GLOBAL_ROUTING_MAX_LAYER)
min_droute_layer = tech_db.findLayer(DETAILED_ROUTING_MIN_LAYER)
max_droute_layer = tech_db.findLayer(DETAILED_ROUTING_MAX_LAYER)

if not all([min_groute_layer, max_groute_layer, min_droute_layer, max_droute_layer]):
    print(f"Error: Required routing layers not found: {GLOBAL_ROUTING_MIN_LAYER}, {GLOBAL_ROUTING_MAX_LAYER}, {DETAILED_ROUTING_MIN_LAYER}, {DETAILED_ROUTING_MAX_LAYER}. Aborting routing.")
else:
    # --- Global Routing ---
    print("Performing global routing...")
    grt = design.getGlobalRouter()

    # Set routing layer ranges
    grt.setMinRoutingLayer(min_groute_layer.getRoutingLevel())
    grt.setMaxRoutingLayer(max_groute_layer.getRoutingLevel())
    grt.setMinLayerForClock(min_groute_layer.getRoutingLevel()) # Use same range for clock
    grt.setMaxLayerForClock(max_groute_layer.getRoutingLevel())
    print(f"Set global routing layers: {GLOBAL_ROUTING_MIN_LAYER} to {GLOBAL_ROUTING_MAX_LAYER}")

    # Set adjustment (congestion control) - example value
    grt.setAdjustment(0.5)
    grt.setVerbose(True) # Enable verbose output

    # Run global routing
    grt.globalRoute(True) # True enables timing-driven global routing
    print("Global routing completed.")

    # --- Detailed Routing ---
    print("Performing detailed routing...")
    drter = design.getTritonRoute()
    params = drt.ParamStruct()

    # Configure parameters for detailed routing
    params.enableViaGen = True # Enable via generation
    params.drouteEndIter = 1 # Number of detailed routing iterations (1 is common)
    params.bottomRoutingLayer = DETAILED_ROUTING_MIN_LAYER
    params.topRoutingLayer = DETAILED_ROUTING_MAX_LAYER
    params.verbose = 1 # Verbosity level
    params.cleanPatches = True # Clean up routing patches
    params.doPa = True # Perform pin access analysis
    params.singleStepDR = False # Run detailed routing in a single step
    params.minAccessPoints = 1 # Minimum access points per pin

    # Optional output files - uncomment if needed
    # params.outputMazeFile = "maze.log"
    # params.outputDrcFile = "drc.rpt"
    # params.outputCmapFile = "cmap.rpt"

    drter.setParams(params)
    # Run detailed routing
    drter.main()
    print("Detailed routing completed.")

# --- Analysis ---
print("\n--- Performing Analysis ---")

# Ensure VDD net exists for IR drop analysis
if VDD_net is None:
     print("Skipping IR drop analysis: VDD net not found.")
else:
    print("Performing static IR drop analysis on VDD net...")
    psm_obj = design.getPDNSim()
    timing = Timing(design) # Get timing object for corners

    # Get a timing corner for analysis
    timing_corner = None
    corners = timing.getCorners()
    if corners:
        timing_corner = corners[0] # Use the first available corner
        print(f"Using timing corner '{timing_corner.getName()}' for IR drop analysis.")
    else:
        print("Warning: No timing corners found for IR drop analysis.")

    # Source types for analysis, using STRAPS as power comes from generated grids/straps
    analysis_source_type = psm.GeneratedSourceType_STRAPS

    if timing_corner:
        # The API analyzePowerGrid analyzes the entire grid connected to the net.
        # "on M1 nodes" is not a direct parameter; the analysis covers all layers including M1.
        try:
            psm_obj.analyzePowerGrid(net=VDD_net,
                                     enable_em=False, # Disable electromigration analysis
                                     corner=timing_corner,
                                     use_prev_solution=False,
                                     source_type=analysis_source_type)
            print("IR drop analysis completed.")
        except Exception as e:
            print(f"Error during IR drop analysis: {e}")
            # Continue script if IR drop analysis is not critical to the rest of the flow
    else:
        print("Skipping IR drop analysis: No timing corner available.")

# Report power (switching, leakage, internal, total)
print("Reporting power...")
try:
    # Redirect report_power output to a file
    design.evalTclString(f"redirect {POWER_REPORT_FILE} {{report_power}}")
    print(f"Power report generated: {POWER_REPORT_FILE}")
except Exception as e:
    print(f"Error running report_power: {e}")
    print("Skipping power report.")


# --- Output ---
print("\n--- Writing Output Files ---")
# Write final DEF file
print(f"Writing DEF file: {FINAL_DEF_FILE}...")
try:
    design.writeDef(FINAL_DEF_FILE)
    print("DEF file written.")
except Exception as e:
    print(f"Error writing DEF file: {e}")

# Write final ODB database file
print(f"Writing ODB file: {FINAL_ODB_FILE}...")
try:
    design.writeDb(FINAL_ODB_FILE)
    print("ODB file written.")
except Exception as e:
    print(f"Error writing ODB file: {e}")

print("\n--- Script Finished ---")