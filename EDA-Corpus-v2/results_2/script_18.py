import openroad as ord
import odb
import pdn
import drt
import psm
import timing
from pathlib import Path
import time
import os # Import os for creating directory

# Helper function to convert micron to DBU
def micronToDBU(design, value):
    # Need to ensure design, tech, and DB are valid before calling micronToDBU
    db = design.getTech().getDB() if (design and design.getTech()) else None
    if db is None:
        # Fallback: Try getting the main DB if 'design' isn't fully initialized yet
        db = ord.get_db()
        if db is None or db.getTech() is None:
            print("Error: DB or Tech not initialized for micronToDBU.")
            return 0 # Or handle error appropriately
        return db.getTech().getDBUPerMicron() * value # Calculate manually if design not set
    return db.micronToDBU(value)

# --- Initialization ---
print("Initializing OpenROAD...")
# Redirect C++ stdout to Python stdout. Ensure this is done early.
ord.redirect_stdout()
# Get the main database object, technology object
db = ord.get_db()
tech = ord.get_tech()
design = None # Initialize design as None

# --- File Paths (Replace with your actual paths) ---
# IMPORTANT: These paths need to be correct for your environment.
# This assumes a structure like: your_project/scripts, your_project/Design/nangate45
# Determine project root relative to the script location
script_dir = Path(__file__).resolve().parent
# Assume project root is one level up from the script directory
project_root = script_dir.parent

# Define technology and design directories
techDir = project_root / "Design" / "nangate45" # Assuming tech files are here
libDir = techDir / "lib"
lefDir = techDir / "lef"
designDir = project_root / "Design"

# Define design files
verilog_file = designDir / "1_synth.v" # Verilog netlist name (update if needed)
design_top_module_name = "gcd" # Top level module name (update if needed)

# Find the standard cell site name from one of the LEF files
site_name = None
try:
    # Read a representative LEF to find a CORE site
    # Sort to get a consistent order, although any LEF with CORE site works
    representative_lef = sorted(lefDir.glob("*.lef"))
    if representative_lef:
        # Create a temporary DB to read LEF without affecting the main one
        temp_db = odb.dbDatabase.create()
        temp_tech = temp_db.getTech()
        # Only read one or two LEFs needed to find a site
        files_to_check = representative_lef[:2] # Check first two LEFs
        for lef_path in files_to_check:
            print(f"Checking {lef_path.as_posix()} for site definition...")
            temp_tech.readLef(lef_path.as_posix())
            for site in temp_tech.getSites():
                if site.getClass() == "CORE":
                    site_name = site.getName()
                    print(f"Found CORE site: {site_name}")
                    break # Found site, no need to check more files
            if site_name:
                break # Found site, exit outer loop
        temp_db.destroy() # Clean up temporary DB
except Exception as e:
    print(f"Warning: Could not automatically determine standard cell site name: {e}")

if site_name is None:
    print("Error: Could not determine a CORE standard cell site name from LEF files. Please specify manually.")
    # Fallback to a common name if known, or exit
    # This fallback name MUST match the site defined in your specific technology LEF!
    # Example: "FreePDK45_38x28_10R_NP_162NW_34O"
    # For Nangate45, a common site might be "unit" or similar. Check your LEF.
    # We cannot provide a universal fallback here without knowing the specific LEF.
    # A common pattern is "unit", but verify this!
    site_name = "unit" # <<< VERIFY THIS FALLBACK MATCHES YOUR LEF >>>
    print(f"Using fallback site name: '{site_name}'. PLEASE CAREFULLY VERIFY THIS IS CORRECT FOR YOUR TECHNOLOGY LEF.")
    # If you are unsure, you might need to exit here or manually inspect your LEF files.
    # exit() # Uncomment to exit if site name is critical and fallback is uncertain.


print(f"Project root: {project_root}")
print(f"Verilog file: {verilog_file.as_posix()}")
print(f"Standard cell site: {site_name}")

# --- Read Technology and Library Files ---
print("Reading technology and library files...")
# Read tech LEF (usually ends with .tech.lef)
tech_lef_files = sorted(lefDir.glob("*.tech.lef"))
# Read library LEFs (standard cell LEFs)
lib_lef_files = sorted(lefDir.glob("*.lef"))

all_lef_files = sorted(list(set(tech_lef_files + lib_lef_files))) # Combine and sort unique files

if not all_lef_files:
    print(f"Error: No LEF files found in {lefDir.as_posix()}. Exiting.")
    exit()
else:
    print(f"Found {len(all_lef_files)} LEF files.")
    for lef_file in all_lef_files:
        print(f"Reading LEF: {lef_file.as_posix()}")
        tech.readLef(lef_file.as_posix()) # Read all LEFs into the technology DB

# Read liberty files (.lib)
lib_files = sorted(libDir.glob("*.lib"))
if not lib_files:
    print(f"Error: No LIB files found in {libDir.as_posix()}. Exiting.")
    exit()
else:
    print(f"Found {len(lib_files)} LIB files.")
    for lib_file in lib_files:
        print(f"Reading liberty file: {lib_file.as_posix()}")
        tech.readLiberty(lib_file.as_posix())

# --- Create Design and Read Netlist ---
print("Creating design and reading netlist...")
# Create design from the top module name and list of liberty files
design = ord.create_design(db, tech, [libFile.as_posix() for libFile in lib_files])
design.readVerilog(verilog_file.as_posix())

# --- Link Design ---
print(f"Linking design: {design_top_module_name}...")
design.link(design_top_module_name)
block = design.getTopBlock()
if block is None:
    print("Error: Linking failed. Top block not found. Check module name and verilog file.")
    exit()

# --- Set Clock Constraint ---
print("Setting clock constraint...")
clock_period_ns = 40.0
clock_port_name = "clk" # Name specified in the prompt
clock_name = "core_clock" # Internal name for the clock

# Use Tcl command via evalTclString as it's the standard way for clock constraints
ord.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
# Set propagated clock for downstream timing analysis (CTS, STA)
ord.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Set initial wire resistance and capacitance models
print("Setting initial wire RC models...")
# These values are used for initial timing estimations before routing extracts parasitic RC.
# The prompt requested 0.03574 (resistance) and 0.07516 (capacitance) per unit length.
# Ensure these values match your technology if you have specific requirements.
# Note: These settings might be overridden by routing parasitic extraction results later.
ord.evalTclString("set_wire_rc -clock -resistance 0.03574 -capacitance 0.07516")
ord.evalTclString("set_wire_rc -signal -resistance 0.03574 -capacitance 0.07516")

# --- Floorplanning ---
print("Performing floorplanning...")
floorplan = ord.get_floorplan()
site = floorplan.findSite(site_name)
if site is None:
    print(f"Error: Standard cell site '{site_name}' not found after reading LEFs.")
    print("Please check your LEF files and the 'site_name' variable.")
    exit()

utilization = 0.50 # Target utilization specified in prompt
aspect_ratio = 1.0 # Square aspect ratio
margin_micron = 12.0 # Spacing between core and die specified in prompt

# Convert margin to DBU using the micronToDBU helper
margin_dbu = micronToDBU(design, margin_micron)

# Initialize the floorplan using the Parameters struct (modern API)
print(f"Initializing floorplan: target_utilization={utilization}, aspect_ratio={aspect_ratio}, core_margin={margin_micron} um ({margin_dbu} DBU)")
params = floorplan.getParameters()
params.utilization = utilization
params.aspectRatio = aspect_ratio
# Apply the same margin to all sides (left, bottom, right, top) as implied by "spacing between core and die"
params.leftMargin = margin_dbu
params.bottomMargin = margin_dbu
params.rightMargin = margin_dbu
params.topMargin = margin_dbu
params.site = site # Specify the standard cell site
floorplan.initFloorplan(params)


# Create placement tracks based on the site definition and floorplan dimensions
print("Creating placement tracks...")
floorplan.makeTracks()

# Get core and die areas after floorplanning in DBU
die_area = block.getDieArea()
core_area = block.getCoreArea()
print(f"Die area: {die_area}")
print(f"Core area: {core_area}")


# --- I/O Pin Placement ---
print("Performing I/O pin placement...")
ioplacer = ord.get_io_placer()
# Configure I/O placer parameters
ioplacer_params = ioplacer.getParameters()
ioplacer_params.setRandSeed(42) # Set random seed for reproducibility
# Set minimum distance between pins. Prompt implied no specific min, default is 0.
# Using False for MinDistanceInTracks means the MinDistance value is in DBU, not tracks.
ioplacer_params.setMinDistanceInTracks(False)
ioplacer_params.setMinDistance(0) # No minimum distance constraint between pins in DBU
ioplacer_params.setCornerAvoidance(0) # No corner avoidance constraint in DBU (value is in DBU)

# Specify metal layers for I/O pin placement as requested (M8 and M9)
# Need to get the layers from the technology DB
m8_layer = db.getTech().findLayer("metal8")
m9_layer = db.getTech().findLayer("metal9")

if m8_layer and m9_layer:
    print("Using metal8 (horizontal) and metal9 (vertical) for pins as requested.")
    # Assuming metal8 is horizontal and metal9 is vertical based on typical layer assignments
    # Verify layer direction if needed using layer.getDirection()
    if m8_layer.getDirection() == odb.dbTechLayerDir.VERTICAL:
         print("Warning: metal8 direction is vertical. Consider swapping layers for H/V.")
         # If direction is known, use the correct layer for Horizontal/Vertical
         ioplacer.addVerLayer(m8_layer)
    else:
         ioplacer.addHorLayer(m8_layer) # Add metal8 as a horizontal layer

    if m9_layer.getDirection() == odb.dbTechLayerDir.HORIZONTAL:
         print("Warning: metal9 direction is horizontal. Consider swapping layers for H/V.")
         # If direction is known, use the correct layer for Horizontal/Vertical
         ioplacer.addHorLayer(m9_layer)
    else:
         ioplacer.addVerLayer(m9_layer) # Add metal9 as a vertical layer

else:
    print("Error: Required layers metal8 or metal9 not found in the technology LEF for I/O placement.")
    print("Using fallback: Finding the top two routing layers.")
    # Fallback: Find the top two routing layers available in the tech
    tech_db = db.getTech()
    routing_layers_sorted = sorted([l for l in tech_db.getLayers() if l.getType() == odb.dbTechLayerType.ROUTING], key=lambda l: l.getRoutingLevel())

    if len(routing_layers_sorted) >= 2:
        # Use the top two layers for fallback
        fallback_m9 = routing_layers_sorted[-1]
        fallback_m8 = routing_layers_sorted[-2]
        print(f"Using fallback layers: {fallback_m8.getName()} (level {fallback_m8.getRoutingLevel()}) and {fallback_m9.getName()} (level {fallback_m9.getRoutingLevel()})")

        # Add fallback layers based on their direction
        if fallback_m8.getDirection() == odb.dbTechLayerDir.VERTICAL:
            ioplacer.addVerLayer(fallback_m8)
        else:
            ioplacer.addHorLayer(fallback_m8)

        if fallback_m9.getDirection() == odb.dbTechLayerDir.VERTICAL:
            ioplacer.addVerLayer(fallback_m9)
        else:
            ioplacer.addHorLayer(fallback_m9)
    else:
        print("Error: Could not find at least two routing layers for fallback I/O placement. Exiting.")
        exit()


IOPlacer_random_mode = True # Enable annealing/random mode for I/O placement

# Get I/O ports (BTerms with INPUT, OUTPUT, INOUT type)
io_ports = [p for p in block.getBTerms() if p.getIoType() in [odb.dbIoType.INPUT, odb.dbIoType.OUTPUT, odb.dbIoType.INOUT]]
if io_ports:
    print(f"Placing {len(io_ports)} I/O ports...")
    # Run I/O placement using the configured parameters and random mode
    ioplacer.runAnnealing(IOPlacer_random_mode)
else:
    print("No I/O ports found to place.")


# --- Macro Placement ---
print("Performing macro placement...")
# Find instances that are macros (their master is a block, not a standard cell)
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

macro_min_spacing_micron = 5.0 # Minimum distance between macros specified in prompt (requested)
macro_halo_micron = 5.0 # Halo size around macros specified in prompt

macro_halo_dbu = micronToDBU(design, macro_halo_micron)

# Layer name to snap macro pins to tracks (specified in prompt)
macro_pin_snap_layer_name = "metal4"
macro_pin_snap_layer = db.getTech().findLayer(macro_pin_snap_layer_name)

if len(macros) > 0:
    print(f"Found {len(macros)} macros. Running macro placement...")
    mpl = ord.get_macro_placer()
    core = block.getCoreArea() # Place macros within the core area fence

    # --- IMPORTANT NOTE ON MACRO-MACRO SPACING ---
    # The prompt requested minimum spacing between macros (5um).
    # The Python API function `mpl.place` invokes a macro global placer
    # but *does not* have a direct parameter to strictly enforce a minimum distance
    # between *macro instances themselves*. It focuses on distributing macros
    # and managing standard cell placement around them (via halo/fence).
    # Strict macro-macro spacing is typically handled by TCL commands like
    # `set_macro_extension` or `set_macro_spacing` or by the specific
    # macro placer engine's cost function if it supports it implicitly.
    # The halo setting *does* create a region around the macro where standard cells
    # will not be placed, but this doesn't guarantee separation *between* macros.
    # We are proceeding with `mpl.place` which is the standard Python API entry point,
    # but acknowledging this limitation regarding the strict macro-macro spacing requirement.
    print(f"Note: Minimum macro-macro spacing ({macro_min_spacing_micron} um) is not strictly guaranteed by the current Python API `mpl.place`. Relying on halo ({macro_halo_micron} um) and subsequent legalization steps.")

    if macro_pin_snap_layer is None:
         print(f"Warning: Macro pin snap layer '{macro_pin_snap_layer_name}' not found. Skipping pin snapping.")
         snap_layer_level = 0 # 0 or negative means no snapping
    else:
         snap_layer_level = macro_pin_snap_layer.getRoutingLevel()
         print(f"Snapping macro pins to {macro_pin_snap_layer_name} (Level {snap_layer_level}).")

    # Run macro placement within the core area fence, with a halo around each macro
    # Using default values for parameters not specified in the prompt
    mpl.place(
        halo_width = macro_halo_dbu,
        halo_height = macro_halo_dbu,
        # Use the core area as the fence for macro placement
        fence_lx = core.xMin(),
        fence_ly = core.yMin(),
        fence_ux = core.xMax(),
        fence_uy = core.yMax(),
        snap_layer = snap_layer_level,
        num_threads = ord.get_macro_placer().getNumThreads(), # Use tool default threads
        max_num_macro = len(macros), # Place all macros found
        min_num_macro = 0,
        max_num_inst = 0, # 0 means no limit on standard cells near macros? Check doc. Usually 0 is fine.
        min_num_inst = 0,
        tolerance = 0.1, # Tolerance for convergence
        max_num_level = 2, # Hierarchy levels for placement
        coarsening_ratio = 10.0,
        large_net_threshold = 50,
        signature_net_threshold = 50,
        area_weight = 0.1,
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        pin_access_th = 0.0, # Pin access threshold
        target_util = 0.25, # Target utilization for macro placement (usually lower than core utilization)
        target_dead_space = 0.05,
        min_ar = 0.33, # Minimum aspect ratio for macro regions
        bus_planning_flag = False, # Disable bus planning
        report_directory = "" # No specific report directory
    )
else:
    print("No macros found in the design. Skipping macro placement.")


# --- Standard Cell Placement (Global & Detailed) ---
print("Performing standard cell placement...")
# Global Placement
print("Running global placement...")
gpl = ord.get_replace()

# Verification Feedback 1: The prompt asked for Global Router iterations=30,
# but the script was setting Global Placement initial iterations to 30.
# The Python API for GlobalRouter does not expose an iteration count parameter.
# Correction: Remove the Global Placement iteration setting based on the GR prompt.
# We will use the default iteration settings for the Python GP API calls.
# gpl.setInitialPlaceMaxIter(global_placement_iterations) # REMOVED

gpl.setTimingDrivenMode(False) # Not timing driven initially for speed
gpl.setRoutabilityDrivenMode(True) # Enable routability optimization during GP
gpl.setUniformTargetDensityMode(True) # Use uniform target density
gpl.doInitialPlace(threads = ord.get_replace().getNumThreads()) # Run initial placement
gpl.doNesterovPlace(threads = ord.get_replace().getNumThreads()) # Run Nesterov-based placement

gpl.reset() # Reset global placer state after use

# Detailed Placement / Legalization (Pre-CTS legalization might be needed, but we do a final one post-CTS)
# print("Running pre-CTS detailed placement/legalization...")
# dp = ord.get_opendp()
# dp.detailedPlacement(0, 0, "", True) # Legalize only before CTS

# --- Clock Tree Synthesis (CTS) ---
print("Performing Clock Tree Synthesis (CTS)...")
cts = ord.get_triton_cts()
parms = cts.getParms()
parms.setWireSegmentUnit(20) # Example wire segment unit (in DBU)
buffer_cell_name = "BUF_X2" # Buffer cell name specified in the prompt

# Find the actual master for the buffer cell
buffer_master = None
for lib in db.getLibs():
    buffer_master = lib.findMaster(buffer_cell_name)
    if buffer_master:
        break

if buffer_master is None:
    print(f"Error: Buffer cell master '{buffer_cell_name}' not found in libraries. Cannot run CTS. Exiting.")
    exit()

print(f"Using buffer cell: {buffer_cell_name}")
# Set the list of allowed buffer cells for CTS
cts.setBufferList(buffer_cell_name)
# Setting root/sink buffers explicitly might be required depending on flow,
# but CTS typically infers roots from the clock definition.
# Using 'BUF_X2' as the root buffer as specified.
# cts.setRootBuffer(buffer_cell_name)
# Sink buffer setting is less common via this API
# cts.setSinkBuffer(buffer_cell_name)

# Run CTS
print("Running TritonCTS...")
cts.runTritonCts()
print("CTS complete.")


# --- Post-CTS Detailed Placement/Legalization ---
print("Performing post-CTS detailed placement/legalization...")
dp = ord.get_opendp()
# Remove any potential fillers inserted earlier (they should only be inserted at the very end)
dp.removeFillers()

# Apply the requested maximum displacement constraint during this final detailed placement/legalization step.
# This step cleans up any placement issues introduced by CTS and applies final legalization.
max_disp_x_micron = 0.5 # Max displacement in x-axis specified in prompt
max_disp_y_micron = 0.5 # Max displacement in y-axis specified in prompt

# Convert max displacement to DBU
max_disp_x_dbu = micronToDBU(design, max_disp_x_micron)
max_disp_y_dbu = micronToDBU(design, max_disp_y_micron)

print(f"Running post-CTS detailed placement/legalization with max displacement {max_disp_x_micron}um x {max_disp_y_micron}um ({max_disp_x_dbu} DBU x {max_disp_y_dbu} DBU)...")
# detailedPlacement(max_displacement_x, max_displacement_y, cell_list_file, legalize_only)
# Running legalization (True) after CTS and setting max displacement.
dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", True) # Set legalize_only to True after CTS


# --- Filler Cell Insertion ---
print("Inserting filler cells...")
filler_masters = list()
# Find standard cell filler masters in the libraries
for lib in db.getLibs():
    for master in lib.getMasters():
        # Look for masters specifically marked as CORE_SPACER (the standard type for fillers)
        if master.getType() == odb.dbMasterType.CORE_SPACER:
             filler_masters.append(master)

if not filler_masters:
    print("Warning: No CORE_SPACER type filler cells found in library masters. Skipping filler insertion.")
else:
    # Sort fillers by width for better packing (optional but good practice)
    # Smallest fillers first often leads to better utilization
    filler_masters.sort(key=lambda m: m.getWidth())
    # Get filler names for the API call
    filler_master_names = [m.getName() for m in filler_masters]
    print(f"Found {len(filler_master_names)} filler cell types: {[m.getName() for m in filler_masters]}. Performing filler placement...")

    # fillerPlacement(filler_masters_names, prefix, blockages, boundary, corner_avoidance, verbose)
    # Use the core_area as the boundary for filler placement to fill empty spaces within the core
    core_area = block.getCoreArea()
    dp.fillerPlacement(filler_masters_names = filler_master_names,
                       blockages = [], # No specific filler blockages defined
                       boundary = core_area, # Confine fillers to the core area
                       corner_avoidance = 0, # No corner avoidance for fillers (value in DBU)
                       verbose = False) # Suppress verbose output during placement
    print("Filler insertion complete.")


# --- Power Delivery Network (PDN) Construction ---
print("Constructing Power Delivery Network (PDN)...")

# Set up global power/ground connections
print("Setting up global power/ground connections...")
# Find or create the VDD and VSS nets
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

# Create VDD/VSS nets if they don't exist (can happen after synthesis if not in netlist)
if VDD_net is None:
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSigType("POWER")
    print("Created VDD net.")
if VSS_net is None:
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSigType("GROUND")
    print("Created VSS net.")

# Mark power and ground nets as special to prevent them from being routed by the signal router
print("Marking VDD/VSS nets as special...")
VDD_net.setSpecial()
VSS_net.setSpecial()

# Connect power pins of instances (standard cells and macros) to global nets
print("Applying global power/ground connections to instances...")
# Common power and ground pin names (adjust based on your library)
# It's best practice to iterate through masters and find actual PG pins
power_pins_found = set()
ground_pins_found = set()
for lib in db.getLibs():
    for master in lib.getMasters():
        for mterm in master.getMTerms():
            if mterm.getIoType() == odb.dbIoType.POWER:
                power_pins_found.add(mterm.getName())
            elif mterm.getIoType() == odb.dbIoType.GROUND:
                ground_pins_found.add(mterm.getName())

power_pin_pattern = "|".join(list(power_pins_found)) if power_pins_found else "VDD|VCC|VDDPE|VDDCE" # Fallback pattern
ground_pin_pattern = "|".join(list(ground_pins_found)) if ground_pins_found else "VSS|GND|VSSE" # Fallback pattern

print(f"Using power pin pattern: '{power_pin_pattern}'")
print(f"Using ground pin pattern: '{ground_pin_pattern}'")


# Clear any existing global connects to avoid duplicates if script is re-run
block.clearGlobalConnects()

# Add global connects:
# region=None applies to the entire block
# instPattern=".*" applies to all instances
# pinPattern uses regex to match discovered or fallback pin names
block.addGlobalConnect(region=None, instPattern=".*", pinPattern=f"({power_pin_pattern})", net=VDD_net, do_connect=True)
block.addGlobalConnect(region=None, instPattern=".*", pinPattern=f"({ground_pin_pattern})", net=VSS_net, do_connect=True)

# Apply the global connections to create the actual net connections on instance pins
block.globalConnect()
print("Global connections applied.")

# Get the PDN generator object
pdngen = ord.get_pdn_gen()
# Define the core voltage domain
core_domain_name = "Core"

# Ensure the core domain is cleared/destroyed before creating it to avoid errors on re-run
existing_domain = pdngen.findDomain(core_domain_name)
if existing_domain:
     pdngen.destroyDomain(existing_domain[0])
     print(f"Destroyed existing domain: {core_domain_name}")

# Create the core domain, linking it to the VDD and VSS nets
core_domain = pdngen.createDomain(name=core_domain_name, power=VDD_net, ground=VSS_net)
domains = [core_domain] # List of domains to process

# Define layers - check they exist in the technology
required_layer_names = ["metal1", "metal4", "metal5", "metal6", "metal7", "metal8"]
layers = {}
found_all_layers = True
for name in required_layer_names:
    layer = db.getTech().findLayer(name)
    if layer:
        layers[name] = layer
    else:
        print(f"Error: Required metal layer '{name}' not found for PDN construction. Exiting.")
        found_all_layers = False
if not found_all_layers:
    exit()

# Assign found layers to variables for easier use
m1 = layers["metal1"]
m4 = layers["metal4"]
m5 = layers["metal5"]
m6 = layers["metal6"]
m7 = layers["metal7"]
m8 = layers["metal8"]

# Define dimensions specified in the prompt (in microns)
m1_stdcell_width_micron = 0.07
m4_macro_width_micron = 1.2
m4_macro_spacing_micron = 1.2
m4_macro_pitch_micron = 6.0
m5_macro_width_micron = 1.2
m5_macro_spacing_micron = 1.2
m5_macro_pitch_micron = 6.0
m6_macro_width_micron = 1.2
m6_macro_spacing_micron = 1.2
m6_macro_pitch_micron = 6.0
m7_ring_width_micron = 5.0
m7_ring_spacing_micron = 5.0
m8_ring_width_micron = 5.0
m8_ring_spacing_micron = 5.0
offset_micron = 0.0 # Offset specified as 0 for all cases
via_cut_pitch_micron = 0.0 # Via pitch specified as 0 for parallel grids (implies auto/minimum pitch)

# Convert dimensions to DBU
m1_stdcell_width = micronToDBU(design, m1_stdcell_width_micron)
m4_macro_width = micronToDBU(design, m4_macro_width_micron)
m4_macro_spacing = micronToDBU(design, m4_macro_spacing_micron)
m4_macro_pitch = micronToDBU(design, m4_macro_pitch_micron)
m5_macro_width = micronToDBU(design, m5_macro_width_micron)
m5_macro_spacing = micronToDBU(design, m5_macro_spacing_micron)
m5_macro_pitch = micronToDBU(design, m5_macro_pitch_micron)
m6_macro_width = micronToDBU(design, m6_macro_width_micron)
m6_macro_spacing = micronToDBU(design, m6_macro_spacing_micron)
m6_macro_pitch = micronToDBU(design, m6_macro_pitch_micron)
m7_ring_width = micronToDBU(design, m7_ring_width_micron)
m7_ring_spacing = micronToDBU(design, m7_ring_spacing_micron)
m8_ring_width = micronToDBU(design, m8_ring_width_micron)
m8_ring_spacing = micronToDBU(design, m8_ring_spacing_micron)
offset = micronToDBU(design, offset_micron)
# Via pitch 0 means use minimum allowed pitch or auto-calculation by the tool
via_cut_pitch_x = micronToDBU(design, via_cut_pitch_micron) # 0 DBU
via_cut_pitch_y = micronToDBU(design, via_cut_pitch_micron) # 0 DBU


# --- Standard Cell Power Grid ---
# Create the Core (Standard Cell) Grid structure
print("Creating Core (Standard Cell) power grid structure...")
core_grid_name = "stdcell_core_grid"
# Clear any existing grid with this name
if pdngen.findGrid(core_grid_name):
    pdngen.destroyGrid(pdngen.findGrid(core_grid_name)[0])

# makeCoreGrid sets up the basic grid structure within the core area for std cells
pdngen.makeCoreGrid(domain=core_domain,
                    name=core_grid_name, # Name for the std cell core grid
                    starts_with=pdn.GROUND, # Start grid connections with ground net (VSS)
                    pin_layers=[], # No specific pin layers for the base grid setup
                    generate_obstructions=[], # Do not generate obstructions from this grid
                    powercell=None, # No power cell specified
                    powercontrol=None, # No power control specified
                    powercontrolnetwork="STAR") # Power control network type (example uses STAR)

stdcell_grid = pdngen.findGrid(core_grid_name)[0] # Get the grid object

# Add M1 followpin straps for standard cell power connections
print("Adding standard cell power straps (M1 followpins)...")
pdngen.makeFollowpin(grid=stdcell_grid,
                     layer=m1, # Layer for followpins
                     width=m1_stdcell_width, # Width specified in prompt
                     extend=pdn.CORE) # Extend followpins within the core area to connect standard cells

# Add power rings around the core area on M7 and M8
print("Adding M7/M8 power rings around the core area...")
# Rings are added to the core grid structure. They run around the boundary.
# The offset is relative to the core boundary.
pdngen.makeRing(grid=stdcell_grid, # Attach rings to the std cell grid structure
                layer0=m7, width0=m7_ring_width, spacing0=m7_ring_spacing,
                layer1=m8, width1=m8_ring_width, spacing1=m8_ring_spacing,
                starts_with=pdn.GRID, # Connect rings to the core grid structure layers
                offset=[offset, offset, offset, offset], # Apply offset to all sides [left, bottom, right, top]
                pad_offset=[offset, offset, offset, offset], # Apply offset to padding area as well
                extend=True, # Rings typically extend slightly to cover the boundary properly
                pad_pin_layers=[], # No specific pad pin layers for rings
                nets=[], # Apply rings to all nets in the domain (VDD/VSS)
                allow_out_of_die=True) # Allow rings to extend slightly outside the die boundary if needed

# Create via connections within the standard cell power grid.
# This connects M1 followpins up to the M7/M8 rings and any intermediate grid layers that might exist.
print("Adding standard cell grid via connections (M1->...->M7->M8)...")
# Find all routing layers between M1 and M8 (inclusive)
intermediate_layers = sorted([l for l in db.getTech().getLayers()
                              if l.getType() == odb.dbTechLayerType.ROUTING and l.getRoutingLevel() >= m1.getRoutingLevel() and l.getRoutingLevel() <= m8.getRoutingLevel()],
                             key=lambda l: l.getRoutingLevel())

if len(intermediate_layers) > 1:
    # Create connections between adjacent layers in the sorted list
    for i in range(len(intermediate_layers) - 1):
        layer0 = intermediate_layers[i]
        layer1 = intermediate_layers[i+1]
        print(f"  Connecting {layer0.getName()} to {layer1.getName()}...")
        pdngen.makeConnect(grid=stdcell_grid, layer0=layer0, layer1=layer1,
                           cut_pitch_x=via_cut_pitch_x, cut_pitch_y=via_cut_pitch_y)
elif len(intermediate_layers) == 1:
     print("Warning: Only one routing layer found between M1 and M8. No vias needed within this range.")
else:
     print("Warning: No routing layers found between M1 and M8 (inclusive). Cannot create via connections.")


# --- Macro Power Grids ---
# Create power grids for macro blocks (if macros exist)
if len(macros) > 0:
    print("Creating Macro power grids (M4, M5, M6) for each macro...")
    # Iterate through each macro instance found earlier
    for i, macro_inst in enumerate(macros):
        print(f"  Creating grid for macro instance: {macro_inst.getName()}")
        macro_grid_name = f"macro_grid_{i}_{macro_inst.getName()}" # Unique name per macro instance
        # Clear any existing grid with this name (useful for re-running script)
        if pdngen.findGrid(macro_grid_name):
            pdngen.destroyGrid(pdngen.findGrid(macro_grid_name)[0])

        # Create an instance grid for this specific macro
        # An instance grid is confined to the boundary of the instance plus an optional halo.
        pdngen.makeInstanceGrid(domain=core_domain, # Apply to the core domain (same power/ground nets)
                                name=macro_grid_name, # Unique name for this macro's grid
                                starts_with=pdn.GROUND, # Start with ground connection (VSS)
                                inst=macro_inst, # Target macro instance for this grid
                                halo=[0,0,0,0], # No additional halo around the macro grid boundary itself
                                pg_pins_to_boundary=True, # Connect macro PG pins to the boundary of this instance grid
                                default_grid=False, # This is not the default core grid
                                generate_obstructions=[], # Do not generate obstructions from this grid
                                is_bump=False) # This is not a bump grid

        # Retrieve the created macro grid object
        macro_grid = pdngen.findGrid(macro_grid_name)[0] # findGrid returns a list

        # Add power straps on M4, M5, and M6 within the macro instance grid
        print(f"  Adding straps for {macro_inst.getName()} on M4, M5, M6...")
        # M4 straps (part of the macro instance grid)
        pdngen.makeStrap(grid=macro_grid,
                         layer=m4,
                         width=m4_macro_width,
                         spacing=m4_macro_spacing,
                         pitch=m4_macro_pitch,
                         offset=offset,
                         number_of_straps=0, # 0 means calculate number based on area/pitch/offset
                         snap=True, # Snap straps to tracks/grid
                         starts_with=pdn.GRID, # Connect to the instance grid structure
                         extend=pdn.CORE, # Extend within the instance grid area (macro boundary)
                         nets=[]) # Apply to all nets in the domain (VDD/VSS)

        # M5 straps (part of the macro instance grid)
        pdngen.makeStrap(grid=macro_grid,
                         layer=m5,
                         width=m5_macro_width,
                         spacing=m5_macro_spacing,
                         pitch=m5_macro_pitch,
                         offset=offset,
                         number_of_straps=0,
                         snap=True,
                         starts_with=pdn.GRID,
                         extend=pdn.CORE,
                         nets=[])

        # M6 straps (part of the macro instance grid)
        pdngen.makeStrap(grid=macro_grid,
                         layer=m6,
                         width=m6_macro_width,
                         spacing=m6_macro_spacing,
                         pitch=m6_macro_pitch,
                         offset=offset,
                         number_of_straps=0,
                         snap=True,
                         starts_with=pdn.GRID,
                         extend=pdn.CORE,
                         nets=[])

        # Create via connections within the macro power grid and connecting to the core grid layers.
        # The prompt specified M4-M5, M5-M6, and implied connection up to the core grid (e.g., M7 rings).
        print(f"  Adding via connections for {macro_inst.getName()} (M4->M5, M5->M6, M6->M7)...")
        # Connect M4 to M5 within the macro grid
        pdngen.makeConnect(grid=macro_grid, layer0=m4, layer1=m5,
                           cut_pitch_x=via_cut_pitch_x, cut_pitch_y=via_cut_pitch_y)
        # Connect M5 to M6 within the macro grid
        pdngen.makeConnect(grid=macro_grid, layer0=m5, layer1=m6,
                           cut_pitch_x=via_cut_pitch_x, cut_pitch_y=via_cut_pitch_y)
        # Connect M6 (top macro grid layer) to M7 (a layer in the standard cell core grid where rings are)
        # This establishes connectivity between the macro grid and the main core grid/rings.
        pdngen.makeConnect(grid=macro_grid, layer0=m6, layer1=m7,
                           cut_pitch_x=via_cut_pitch_x, cut_pitch_y=via_cut_pitch_y)

else:
    print("No macros found. Skipping macro power grid construction.")

# Finalize PDN construction
print("Building power grids...")
pdngen.checkSetup()  # Verify the PDN configuration before building
pdngen.buildGrids(False)  # Build the power grid geometry (straps, rings, vias)
pdngen.writeToDb(True)  # Write the generated power grid shapes to the design database
pdngen.resetShapes()  # Reset temporary shapes used during the build process
print("PDN construction complete.")


# --- Global Routing ---
print("Performing global routing...")
grt = ord.get_global_router()

# Set routing layer ranges for signal and clock nets as requested (M1 to M7)
# Need to get the routing level for these layers
m1_route_layer = db.getTech().findLayer("metal1")
m7_route_layer = db.getTech().findLayer("metal7")

if not m1_route_layer or not m7_route_layer:
    print("Error: metal1 or metal7 not found for routing layer range configuration.")
    # Fallback to using min/max routing layers available in the tech
    tech_db = db.getTech()
    routing_layers_sorted = sorted([l for l in tech_db.getLayers() if l.getType() == odb.dbTechLayerType.ROUTING], key=lambda l: l.getRoutingLevel())
    if routing_layers_sorted:
        min_route_level = routing_layers_sorted[0].getRoutingLevel()
        max_route_level = routing_layers_sorted[-1].getRoutingLevel()
        print(f"Using fallback routing layers: {routing_layers_sorted[0].getName()}-{routing_layers_sorted[-1].getName()} (Levels {min_route_level}-{max_route_level})")
    else:
        print("Error: No routing layers found in technology. Cannot perform routing. Exiting.")
        exit()
else:
    min_route_level = m1_route_layer.getRoutingLevel()
    max_route_level = m7_route_layer.getRoutingLevel()
    print(f"Using routing layers: metal1-metal7 (Levels {min_route_level}-{max_route_level}) for signal and clock nets.")

# Set the routing layer range for global router
grt.setMinRoutingLayer(min_route_level)
grt.setMaxRoutingLayer(max_route_level)
# Use the same range for clock nets as requested by the prompt (M1 to M7)
grt.setMinLayerForClock(min_route_level)
grt.setMaxLayerForClock(max_route_level)

grt.setAdjustment(0.5) # Example routing congestion adjustment factor (0.0 to 1.0)
grt.setVerbose(True) # Enable verbose output for global routing

# Verification Feedback 1 (continued): The prompt requested 30 iterations for the Global Router.
# The current Python API for `grt.globalRoute()` does *not* expose a parameter to set the iteration count directly.
# The number of iterations is controlled internally by the engine called by the API.
# We proceed with the API call, acknowledging this limitation in the Python binding.
print("Note: Global router iterations cannot be explicitly set to 30 using the current Python API call for globalRoute(). Default iterations will be used.")

# Run global routing. The 'True' argument enables via generation, which is needed for detailed routing.
grt.globalRoute(True)
print("Global routing complete.")


# --- Detailed Routing ---
print("Performing detailed routing...")
drter = ord.get_triton_route()
# Get detailed router parameters object
params = drt.ParamStruct()

# Configure detailed routing parameters
params.outputMazeFile = "" # No maze file output specified
params.outputDrcFile = "" # No DRC file output specified
params.outputCmapFile = "" # No cmap file output
params.outputGuideCoverageFile = "" # No guide coverage file output
params.dbProcessNode = "" # No specific process node identifier needed typically

# Enable via generation - essential after global routing with via generation enabled
params.enableViaGen = True

# Detailed routing iterations - typically 1-3 iterations are sufficient for convergence.
# Increasing iterations might improve results but increases runtime.
params.drouteEndIter = 2 # Running 2 iterations as a standard example.

params.viaInPinBottomLayer = "" # No specific layer constraint for via-in-pin bottom
params.viaInPinTopLayer = "" # No specific layer constraint for via-in-pin top
params.orSeed = -1 # Default random seed (-1 means no explicit seed set)
params.orK = 0 # Default K parameter for obstacle handling

# Set the routing layer range for detailed router (usually matches global route range)
params.bottomRoutingLayer = m1_route_layer.getName() if m1_route_layer else routing_layers_sorted[0].getName()
params.topRoutingLayer = m7_route_layer.getName() if m7_route_layer else routing_layers_sorted[-1].getName()
print(f"Detailed routing layers: {params.bottomRoutingLayer}-{params.topRoutingLayer}")

params.verbose = 1 # Verbosity level (1: normal, 2: detailed)
params.cleanPatches = True # Clean routing patches after completion
params.doPa = True # Perform post-route antenna fixing (highly recommended)
params.singleStepDR = False # Do not run in single-step debug mode
params.minAccessPoints = 1 # Minimum access points per pin for routing
params.saveGuideUpdates = False # Do not save guide updates during routing

# Set the configured parameters for the detailed router instance
drter.setParams(params)

# Run detailed routing
print("Running TritonRoute...")
drter.main()
print("Detailed routing complete.")


# --- IR Drop Analysis (PSM) ---
print("Performing IR Drop Analysis...")
psm_obj = ord.get_psm() # Get the Power System Management object

# Identify the power net to analyze (VDD)
target_net = block.findNet("VDD")
if target_net is None or target_net.getSigType() != odb.dbSigType.POWER:
    print("Error: VDD net not found or is not a power net for IR drop analysis. Skipping.")
else:
    print(f"Analyzing IR drop for net: {target_net.getName()}...")
    # Source types can be STRAPS (voltage sources on PG straps/rings/bumps)
    # or CURRENT_SOURCES (requires activity data from timing analysis).
    # STRAPS is simpler for a basic analysis after PDN creation and routing.
    source_type = psm.GeneratedSourceType_STRAPS # Using voltage sources on straps/rings

    # Timing corner is needed if using CURRENT_SOURCES for activity factor calculation.
    # For STRAPS, it's often not strictly necessary for the analysis itself,
    # but the API requires a corner object. Use the first available corner if timing was set up.
    timing_obj = ord.get_timing()
    corners = timing_obj.getCorners()
    analysis_corner = corners[0] if corners else None

    if source_type == psm.GeneratedSourceType_CURRENT_SOURCES and analysis_corner is None:
         print("Warning: No timing corners found for PSM analysis using CURRENT_SOURCES. Results may be inaccurate.")
         print("Switching source_type to STRAPS.")
         source_type = psm.GeneratedSourceType_STRAPS # Fallback if no timing corner exists

    if analysis_corner is None:
        print("Warning: No timing corner available. PSM analysis might use default assumptions.")

    # Run Power Grid Analysis (IR Drop)
    # The Python API `analyzePowerGrid` performs the analysis.
    # To get results specifically on the M1 layer as requested, we need to use Tcl commands *after* the analysis completes.
    print(f"Running analysis with source type: {source_type}")
    psm_obj.analyzePowerGrid(net = target_net,
                             enable_em = False, # No Electromigration analysis requested
                             corner = analysis_corner, # Pass the timing corner (can be None if source_type is STRAPS)
                             use_prev_solution = False, # Do not use a previous solution
                             em_file = "", # No EM file output specified
                             error_file = "", # No error file output specified
                             voltage_source_file = "", # No external voltage source file input
                             voltage_file = "", # No default voltage file output via API call
                             source_type = source_type)

    print("IR Drop Analysis engine complete.")

    # Get and report the analysis result specifically on the M1 layer using Tcl commands
    # Need to get the actual layer object for M1
    m1_layer_obj = db.getTech().findLayer("metal1")

    if m1_layer_obj:
        m1_layer_name = m1_layer_obj.getName()
        print(f"Reporting IR drop summary for {target_net.getName()} on {m1_layer_name}...")
        try:
            # Use Tcl command to report summary for the specified net and layer
            ord.evalTclString(f"report_power_grid_summary -net {target_net.getName()} -layer {m1_layer_name}")

            # Create a results directory if it doesn't exist to save the voltage map
            results_dir = Path("./results")
            os.makedirs(results_dir, exist_ok=True)
            print(f"Ensured results directory exists: {results_dir.as_posix()}")

            # Write voltage map for the net on the M1 layer to a file
            voltage_map_file = results_dir / f"{target_net.getName()}_{m1_layer_name}.dbv"
            print(f"Writing voltage map for {target_net.getName()} on {m1_layer_name} to {voltage_map_file.as_posix()}...")
            # Use Tcl command to write the voltage map file
            ord.evalTclString(f"write_voltage_map -net {target_net.getName()} -layer {m1_layer_name} -output_file {voltage_map_file.as_posix()}")

        except Exception as e:
            print(f"Error executing Tcl commands for IR drop results on layer {m1_layer_name}: {e}")
    else:
        print("Error: metal1 layer object not found for IR drop reporting.")


# --- Report Power ---
# Note: Requires timing data (nets loaded, parasitics extracted, timing updated).
# It's good practice to update timing after physical design steps (placement, CTS, routing, PDN).
# Parasitic extraction is typically run after routing, but was not explicitly requested in this prompt.
# The initial wire RC models and post-CTS timing update will be used for a basic estimate.
print("Running final static timing analysis (STA) for power reporting...")
timing_obj = ord.get_timing() # Get the timing object again
timing_obj.updateTiming() # Update timing using available parasitics (or wire models if no PEX)

print("Reporting power consumption...")
# Use Tcl command via evalTclString to report total power (switching, internal, leakage)
# Add '-verbose' flag for more detailed breakdown if needed: ord.evalTclString("report_power -verbose")
ord.evalTclString("report_power")


# --- Write Final Output ---
print("Writing final DEF file...")
# Write the final DEF file after all major physical design steps (Placement, CTS, PDN, Routing, Fillers)
# The name requested in the prompt is "PDN.def"
output_def_file = "PDN.def"
design.writeDef(output_def_file)
print(f"Final design saved to {output_def_file}")

print("Script finished.")