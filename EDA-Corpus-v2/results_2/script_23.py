from openroad import Tech, Design, Timing
from pathlib import Path
import odb
import pdn
import cts
import drt
import openroad as ord
import power_decap # Import for IR drop analysis
import sta # Import for STA and power reporting

# --- 1. Setup: Paths, Tech/Lib/LEF, Verilog ---
# Set paths to library and design files.
# Assuming standard directory structure relative to the script.
# User should modify these paths as needed for their environment.
design_name = "design" # Assume generic design name
design_top_module_name = "top" # Assume generic top module name
tech_name = "nangate45" # Assume technology name

# Attempt to find tech/lib/lef based on common examples or user input structure
# Adjust these paths based on your file locations
# Use absolute paths or paths relative to the script's execution directory
script_dir = Path(__file__).parent # Directory containing the script
tech_dir = script_dir / f"../Design/{tech_name}"
lib_dir = tech_dir / "lib"
lef_dir = tech_dir / "lef"
verilog_file = script_dir / f"../Design/{design_name}/{design_name}.v" # Assuming verilog is in design specific folder

# Check if directories/files exist (optional but good practice)
if not lib_dir.exists() or not lib_dir.is_dir():
    print(f"Error: Library directory not found at {lib_dir.resolve()}")
    exit(1) # Exit on critical error
if not lef_dir.exists() or not lef_dir.is_dir():
     print(f"Error: LEF directory not found at {lef_dir.resolve()}")
     exit(1) # Exit on critical error
if not verilog_file.exists():
     print(f"Error: Verilog file not found at {verilog_file.resolve()}")
     exit(1) # Exit on critical error


print("--- Reading Tech and Libraries ---")
# Initialize OpenROAD objects and read technology files
tech = Tech()
db = ord.get_db() # Get the database object

# Read all liberty (.lib) and LEF files
lib_files = sorted(list(lib_dir.glob("*.lib"))) # Sort for consistent order
tech_lef_files = sorted(list(lef_dir.glob("*.tech.lef")))
cell_lef_files = sorted(list(lef_dir.glob("*.lef")))

if not lib_files: print(f"Warning: No .lib files found in {lib_dir.resolve()}")
if not tech_lef_files: print(f"Warning: No .tech.lef files found in {lef_dir.resolve()}")
if not cell_lef_files: print(f"Warning: No .lef files found in {lef_dir.resolve()}")

# Load technology and cell LEF files first
for tech_lef_file in tech_lef_files:
    print(f"Reading Tech LEF: {tech_lef_file.resolve()}")
    tech.readLef(tech_lef_file.as_posix())
for cell_lef_file in cell_lef_files:
    # Avoid re-reading tech LEF if it ends in .lef as well
    if not cell_lef_file.name.endswith(".tech.lef"):
        print(f"Reading Cell LEF: {cell_lef_file.resolve()}")
        tech.readLef(cell_lef_file.as_posix())

# Load liberty timing libraries
# Liberty files are typically loaded after LEF in standard flow
for lib_file in lib_files:
    print(f"Reading Liberty: {lib_file.resolve()}")
    tech.readLiberty(lib_file.as_posix())


print("--- Reading Verilog and Linking Design ---")
# Create design and read Verilog netlist
design = Design(tech)
print(f"Reading Verilog: {verilog_file.resolve()}")
design.readVerilog(verilog_file.as_posix())
# Link the top module
print(f"Linking design top module: {design_top_module_name}")
design.link(design_top_module_name)


# --- 2. Clock Configuration ---
print("--- Setting Clock Constraints ---")
clock_period_ns = 40.0
clock_port_name = "clk" # As specified in the prompt
clock_name = "core_clock" # Assign a name to the clock object

# Verify if the clock port exists
if design.getBlock().findPort(clock_port_name) is None:
    print(f"Error: Clock port '{clock_port_name}' not found in the design. Cannot set clock constraint.")
    exit(1) # Exit on critical error


# Create clock signal using Tcl interface (common practice)
print(f"Creating clock on port '{clock_port_name}' with period {clock_period_ns} ns, named '{clock_name}'")
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")

# Propagate the clock signal (needed for timing analysis after placement/CTS)
# Note: This should ideally be done *after* placement/CTS for actual delay calculation.
# For initial setup, setting ideal_network is more common before CTS.
# Setting propagated clock before CTS tells STA to expect propagated delays later.
print(f"Setting clock '{clock_name}' as propagated")
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")


# --- 3. Floorplan ---
print("--- Initializing Floorplan ---")
floorplan = design.getFloorplan()

# Define die and core areas in microns
die_lx_um, die_ly_um = 0.0, 0.0
die_ux_um, die_uy_um = 45.0, 45.0
core_lx_um, core_ly_um = 5.0, 5.0
core_ux_um, core_uy_um = 40.0, 40.0

# Convert micron dimensions to database units (DBU)
die_area = odb.Rect(design.micronToDBU(die_lx_um), design.micronToDBU(die_ly_um),
                    design.micronToDBU(die_ux_um), design.micronToDBU(die_uy_um))
core_area = odb.Rect(design.micronToDBU(core_lx_um), design.micronToDBU(core_ly_um),
                     design.micronToDBU(core_ux_um), design.micronToDBU(core_uy_um))

# Find a site definition from the loaded LEF files
# This is technology specific. Replace with a valid site name from your LEF.
# Example site names from Nangate45: "FreePDK45_38x28_10R_NP_162NW_34O", "FreePDK45_38x28_RFNM"
# Let's try to find a site. A common name might be "CORE" or "STDCELL".
# If none found, take the first site available.
site = None
tech_db = db.getTech() # Use the global db object to get tech
for s in tech_db.getSites():
    if s.getName().upper() in ["CORE", "STDCELL"]:
        site = s
        print(f"Found common site name: {site.getName()}")
        break
if site is None:
     for s in tech_db.getSites():
         site = s
         print(f"Using first available site: {site.getName()}")
         break

if site is None:
    print("Error: No sites found in the loaded LEF files. Cannot initialize floorplan.")
    exit(1) # Exit on critical error


# Initialize floorplan with specified die and core areas and site
print(f"Initializing floorplan with Die: {die_area} DBU, Core: {core_area} DBU, Site: {site.getName()}")
floorplan.initFloorplan(die_area, core_area, site)

# Make routing tracks
print("Making routing tracks")
# This function requires the site to be set correctly during floorplan initialization
floorplan.makeTracks()


# --- 4. Placement ---
print("--- Starting Placement Stages ---")

# Get list of macros in the design
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

# If macros exist, configure and run macro placement
if len(macros) > 0:
    print(f"Found {len(macros)} macros. Performing macro placement.")
    mpl = design.getMacroPlacer()

    # Define macro placement parameters in microns
    macro_halo_width_um = 5.0
    macro_halo_height_um = 5.0
    macro_min_spacing_um = 5.0 # Macro-to-macro spacing
    macro_fence_lx_um, macro_fence_ly_um = 5.0, 5.0
    macro_fence_ux_um, macro_fence_uy_um = 20.0, 25.0

    # Set MacroPlacer parameters that are typically set via dedicated methods
    # The prompt asks for these values, but mpl.place method might take them directly.
    # However, setting them via methods is the standard OpenROAD API practice where available.
    # mpl.setHalo(design.micronToDBU(macro_halo_width_um), design.micronToDBU(macro_halo_height_um)) # Halo set via place args
    # mpl.setFence(odb.Rect(design.micronToDBU(macro_fence_lx_um), design.micronToDBU(macro_fence_ly_um),
    #                       design.micronToDBU(macro_fence_ux_um), design.micronToDBU(macro_fence_uy_um))) # Fence set via place args

    # Set macro-to-macro minimum spacing
    macro_min_spacing_dbu = design.micronToDBU(macro_min_spacing_um)
    mpl.setMacroMacroSpacing(macro_min_spacing_dbu)

    # Run Macro Placement
    # Using parameters specified in the prompt. Other parameters default or from examples.
    # Note: mpl.place method in Python takes micron values for geometry parameters
    print(f"Running Macro Placement with Halo: {macro_halo_width_um}x{macro_halo_height_um} um, Min Spacing: {macro_min_spacing_um} um (set), Fence: ({macro_fence_lx_um},{macro_fence_ly_um}) to ({macro_fence_ux_um},{macro_fence_uy_um}) um")
    mpl.place(
        halo_width = macro_halo_width_um,
        halo_height = macro_halo_height_um,
        fence_lx = macro_fence_lx_um,
        fence_ly = macro_fence_ly_um,
        fence_ux = macro_fence_ux_um,
        fence_uy = macro_fence_uy_um,
        # Use reasonable defaults/example values for unspecified parameters as in original script
        num_threads = ord.get_parallel_threads(), # Use number of threads set for OpenROAD
        max_num_macro = len(macros),
        min_num_macro = 0,
        max_num_inst = 0,
        min_num_inst = 0,
        tolerance = 0.1,
        max_num_level = 2,
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
        pin_access_th = 0.0,
        target_util = 0.5,
        target_dead_space = 0.05,
        min_ar = 0.33,
        snap_layer = 4, # Example snap layer, assuming metal4 exists
        bus_planning_flag = False,
        report_directory = "" # No report directory
    )
    print("Macro Placement finished.")
else:
    print("No macros found. Skipping macro placement.")


# Configure and run global placement
gpl = design.getReplace()
# User asked for 30 iterations for the global router, which likely meant initial global placer iterations.
global_placement_iterations = 30
print(f"Setting Global Placement initial iterations to {global_placement_iterations}")
gpl.setInitialPlaceMaxIter(global_placement_iterations)

# Example parameters for global placer (using reasonable defaults)
# Timing-driven placement is usually enabled after initial setup and timing analysis
gpl.setTimingDrivenMode(False)
# Routability-driven placement is generally beneficial
gpl.setRoutabilityDrivenMode(True)
# Uniform target density is a common setting
gpl.setUniformTargetDensityMode(True)
# Set an initial density penalty factor
gpl.setInitDensityPenalityFactor(0.05)

print("Performing initial Global Placement...")
# Initial placement (e.g., random or simple quadratic)
gpl.doInitialPlace(threads = ord.get_parallel_threads())
print("Performing Nesterov Global Placement...")
# Nesterov-accelerated gradient method for global placement
gpl.doNesterovPlace(threads = ord.get_parallel_threads())
gpl.reset() # Reset placer state after use to release memory/resources
print("Global Placement finished.")


# Run initial detailed placement (before CTS)
opendp = design.getOpendp()
# Detailed placement requires a site to align cells, check again just in case
if site is None:
     print("Error: Site not found for detailed placement after floorplan.")
     exit(1) # Exit on critical error

# Define max displacement in microns
max_disp_x_um = 1.0
max_disp_y_um = 3.0

# Convert max displacement to DBU
# detailedPlacement API takes DBU directly
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

print(f"Performing initial Detailed Placement with max displacement: {max_disp_x_um} um (X), {max_disp_y_um} um (Y)")

# Remove filler cells if they exist (often inserted by previous tools or saved state)
# This allows standard cells to move into filler space before initial DP
filler_masters_count = 0
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters_count += 1
            break
    if filler_masters_count > 0:
        break

if filler_masters_count > 0:
     print("Removing existing filler cells before initial DP...")
     opendp.removeFillers()
else:
    print("No filler cells found to remove before initial DP.")

# Perform detailed placement
# Arguments: max_disp_x_dbu, max_disp_y_dbu, report_file, skip_io_placement
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Initial Detailed Placement finished.")


# --- 5. Clock Tree Synthesis (CTS) ---
print("--- Starting CTS ---")
# Set wire RC values for clock and signal nets (required for accurate CTS timing)
resistance_per_unit = 0.03574
capacitance_per_unit = 0.07516
print(f"Setting wire RC values: R={resistance_per_unit}, C={capacitance_per_unit}")
# Note: OpenROAD's API might offer a direct way to set this on the tech object or timing setup
# Using evalTclString for set_wire_rc is standard in many scripts.
design.evalTclString(f"set_wire_rc -clock -resistance {resistance_per_unit} -capacitance {capacitance_per_unit}")
design.evalTclString(f"set_wire_rc -signal -resistance {resistance_per_unit} -capacitance {capacitance_per_unit}")


# Configure and run clock tree synthesis
cts_tool = design.getTritonCts()

# Set clock buffers
cts_buffer_cell = "BUF_X2" # Assuming "BUF_X2" is a valid buffer cell name in your library
buffer_master = db.findMaster(cts_buffer_cell)
if buffer_master is None:
     print(f"Error: Buffer cell '{cts_buffer_cell}' not found in library. Cannot proceed with CTS.")
     exit(1) # Exit on critical error
else:
    print(f"Using buffer cell: {cts_buffer_cell}")
    # Set buffer list for tree construction
    cts_tool.setBufferList(cts_buffer_cell)
    # Set buffer used for root and sinks if different, otherwise set to the same
    cts_tool.setRootBuffer(cts_buffer_cell)
    cts_tool.setSinkBuffer(cts_buffer_cell)

# Set clock nets for CTS
clock_net = design.getBlock().findNet(clock_name)
if clock_net is None:
     print(f"Error: Clock net '{clock_name}' not found. Cannot perform CTS.")
     exit(1) # Exit on critical error

print(f"Performing CTS on clock net: {clock_name}")
# cts_tool.setClockNets(clock_name) # Pass the name as a string or list of strings
cts_tool.setClockNets([clock_name]) # Use a list as expected by the API

# Optional: Configure CTS parameters (using defaults or example values)
# parms = cts_tool.getParms()
# parms.setWireSegmentUnit(20) # Example wire segment unit in DBU

# Run CTS
cts_tool.runTritonCts()
print("CTS finished.")


# --- 6. Post-CTS Detailed Placement ---
print("--- Performing Final Detailed Placement (Post-CTS) ---")
# Run final detailed placement after CTS to legalize positions of inserted buffers
# Max displacement values are already defined
# Arguments: max_disp_x_dbu, max_disp_y_dbu, report_file, skip_io_placement
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Final Detailed Placement finished.")


# --- 7. Filler Cell Insertion ---
print("--- Inserting Filler Cells ---")
# Insert filler cells to fill gaps in rows and meet density requirements
filler_masters = list()
filler_cells_prefix = "FILLCELL_" # Prefix for inserted filler instance names

# Find all CORE_SPACER masters
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

if not filler_masters: # Check if the list is empty
    print("No filler cells found in library ('CORE_SPACER' type). Skipping filler placement.")
else:
    print(f"Inserting filler cells (found {len(filler_masters)} types).")
    # Use the list of masters directly
    opendp.fillerPlacement(filler_masters = filler_masters,
                           prefix = filler_cells_prefix,
                           verbose = False) # Set to True for more output
    print("Filler cell insertion finished.")


# --- 8. Power Delivery Network (PDN) ---
print("--- Building Power Delivery Network ---")
pdngen = design.getPdnGen()

# Set up global power/ground connections
# Ensure VDD and VSS nets exist and are marked as special
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")

if VDD_net is None:
    VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
    print("Created VDD net.")
# Ensure net type and special flag are set
if not VDD_net.getSigType().isSupply():
    VDD_net.setSigType("POWER")
    print("Set VDD net type to POWER.")
if not VDD_net.isSpecial():
     VDD_net.setSpecial()
     print("Marked VDD net as special.")


if VSS_net is None:
    VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
    print("Created VSS net.")
# Ensure net type and special flag are set
if not VSS_net.getSigType().isSupply():
    VSS_net.setSigType("GROUND")
    print("Set VSS net type to GROUND.")
if not VSS_net.isSpecial():
    VSS_net.setSpecial()
    print("Marked VSS net as special.")

# Add global connects for power and ground pins using the actual net objects
print("Adding global connects for VDD/VSS pins...")
# Map standard VDD/VSS pins to power/ground nets
# Assumes pin names like VDD, VSS, VDDPE, VSSPE, VDDCE, VSSCE are standard
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD.*$", net = VDD_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS.*$", net = VSS_net, do_connect = True)


# Apply the global connections - this physically connects the pins to the nets
print("Applying global connections...")
design.getBlock().globalConnect()


# Configure core power domain (standard cells)
# Find or create the "Core" domain
core_domain = pdngen.findDomain("Core")
if core_domain is None:
    # A domain needs a primary power and ground net
    core_domain = pdngen.makeDomain("Core", domain_type=pdn.DOMAIN_CORE)
    print("Created 'Core' PDN domain.")

print("Setting up core PDN domain with VDD/VSS as primary nets...")
# This call actually associates the nets with the domain
pdngen.setCoreDomain(power = VDD_net, ground = VSS_net)

# Get metal layers for PDN construction
# Ensure these layer names exist in your tech LEF
layer_names = ["metal1", "metal4", "metal5", "metal6", "metal7", "metal8"]
layers = {}
for name in layer_names:
    layer = db.getTech().findLayer(name)
    if layer is None:
        print(f"Error: Metal layer '{name}' not found in technology file. Cannot build PDN.")
        exit(1) # Exit on critical error
    layers[name] = layer

m1, m4, m5, m6, m7, m8 = layers["metal1"], layers["metal4"], layers["metal5"], layers["metal6"], layers["metal7"], layers["metal8"]


# Define dimensions in microns as per prompt
# Core Grid (Standard Cells)
# Note: Prompt mentioned M7/M8 for rings and M1/M4 for straps for std cells.
# The M7/M8 parameters might be for straps, not rings, based on typical flow, but following prompt explicitly.
stdcell_ring_width_um = 5.0 # For M7/M8 rings around core area
stdcell_ring_spacing_um = 5.0 # For M7/M8 rings around core area
stdcell_m1_strap_width_um = 0.07
stdcell_m4_strap_width_um = 1.2
stdcell_m4_strap_spacing_um = 1.2
stdcell_m4_strap_pitch_um = 6.0
stdcell_m7_strap_width_um = 1.4
stdcell_m7_strap_spacing_um = 1.4
stdcell_m7_strap_pitch_um = 10.8
stdcell_m8_strap_width_um = 1.4 # Assuming M8 straps similar to M7 if used, but prompt says M7/M8 rings AND M7/M8 straps. Clarifying M8 straps based on M7 parameters.
stdcell_m8_strap_spacing_um = 1.4
stdcell_m8_strap_pitch_um = 10.8

# Macro Instance Grid (Macros) - Only if macros exist
# Note: Prompt mentioned M5/M6 for rings AND grids/straps for macros.
macro_ring_width_um = 1.5 # For M5/M6 rings around macro instances
macro_ring_spacing_um = 1.5 # For M5/M6 rings around macro instances
macro_strap_width_um = 1.2 # For M5/M6 straps inside macro instances
macro_strap_spacing_um = 1.2 # For M5/M6 straps inside macro instances
macro_strap_pitch_um = 6.0 # For M5/M6 straps inside macro instances

# Common PDN parameters
offset_um = 0.0 # Offset for all cases from boundary/pitch zero point
via_cut_pitch_um = 0.0 # Via pitch between two parallel grids - 0 means auto/default

# Convert micron dimensions to DBU
stdcell_ring_width_dbu = design.micronToDBU(stdcell_ring_width_um)
stdcell_ring_spacing_dbu = design.micronToDBU(stdcell_ring_spacing_um)
stdcell_m1_strap_width_dbu = design.micronToDBU(stdcell_m1_strap_width_um)
stdcell_m4_strap_width_dbu = design.micronToDBU(stdcell_m4_strap_width_um)
stdcell_m4_strap_spacing_dbu = design.micronToDBU(stdcell_m4_strap_spacing_um)
stdcell_m4_strap_pitch_dbu = design.micronToDBU(stdcell_m4_strap_pitch_um)
stdcell_m7_strap_width_dbu = design.micronToDBU(stdcell_m7_strap_width_um)
stdcell_m7_strap_spacing_dbu = design.micronToDBU(stdcell_m7_strap_spacing_um)
stdcell_m7_strap_pitch_dbu = design.micronToDBU(stdcell_m7_strap_pitch_um)
stdcell_m8_strap_width_dbu = design.micronToDBU(stdcell_m8_strap_width_um)
stdcell_m8_strap_spacing_dbu = design.micronToDBU(stdcell_m8_strap_spacing_um)
stdcell_m8_strap_pitch_dbu = design.micronToDBU(stdcell_m8_strap_pitch_um)

macro_ring_width_dbu = design.micronToDBU(macro_ring_width_um)
macro_ring_spacing_dbu = design.micronToDBU(macro_ring_spacing_um)
macro_strap_width_dbu = design.micronToDBU(macro_strap_width_um)
macro_strap_spacing_dbu = design.micronToDBU(macro_strap_spacing_um)
macro_strap_pitch_dbu = design.micronToDBU(macro_strap_pitch_um)

offset_dbu = design.micronToDBU(offset_um)
via_cut_pitch_dbu = design.micronToDBU(via_cut_pitch_um) # 0 um via pitch means default via pitch

# Create power grid for standard cells (Core Grid)
print("Creating Core PDN Grid for standard cells...")
# The core grid covers the core area defined in floorplan
pdngen.makeCoreGrid(domain = core_domain,
                    name = "core_grid",
                    starts_with = pdn.GROUND, # Specify which net starts first based on typical row pattern
                    # pin_layers and generate_obstructions not specified in prompt
                    # powercell, powercontrol not specified
                    # powercontrolnetwork default is 'STAR'
                    )

core_grid = pdngen.findGrid("core_grid")
if core_grid is not None:
    # Add rings on M7 and M8 around the core area
    print("Adding M7/M8 rings to core grid around core boundary...")
    # Ring offsets are relative to the core boundary
    pdngen.makeRing(grid = core_grid,
                    layer0 = m7, width0 = stdcell_ring_width_dbu, spacing0 = stdcell_ring_spacing_dbu,
                    layer1 = m8, width1 = stdcell_ring_width_dbu, spacing1 = stdcell_ring_spacing_dbu,
                    starts_with = pdn.GRID, # Match grid pattern (alternating VDD/VSS)
                    offset = [offset_dbu]*4, # 0 offset from core boundary: [left, bottom, right, top]
                    pad_offset = [offset_dbu]*4, # 0 pad offset: [left, bottom, right, top]
                    extend = False, # Rings stay within the specified boundary (core area)
                    pad_pin_layers = [], # No connection to pads specified
                    nets = []) # Use grid nets (VDD/VSS)

    # Add followpin straps on M1 (typically horizontal) connected to standard cell power rails
    # M1 is commonly used for connecting to standard cell power rails (followpin)
    print("Adding M1 followpin straps to core grid...")
    pdngen.makeFollowpin(grid = core_grid,
                         layer = m1,
                         width = stdcell_m1_strap_width_dbu,
                         extend = pdn.CORE) # Extend across the core area boundary

    # Add strap patterns on M4, M7, M8
    # M4 straps (typically vertical based on site orientation, but depends on tech)
    print("Adding M4 straps to core grid...")
    pdngen.makeStrap(grid = core_grid,
                     layer = m4,
                     width = stdcell_m4_strap_width_dbu,
                     spacing = stdcell_m4_strap_spacing_dbu,
                     pitch = stdcell_m4_strap_pitch_dbu,
                     offset = offset_dbu, # Offset from the start point
                     number_of_straps = 0, # Auto-calculate number based on pitch/area
                     snap = False, # Do not snap to grid/tracks
                     starts_with = pdn.GRID, # Match grid pattern for VDD/VSS
                     extend = pdn.CORE, # Extend across the core area boundary
                     nets = []) # Use grid nets

    # M7 straps (typically horizontal)
    print("Adding M7 straps to core grid...")
    pdngen.makeStrap(grid = core_grid,
                     layer = m7,
                     width = stdcell_m7_strap_width_dbu,
                     spacing = stdcell_m7_strap_spacing_dbu,
                     pitch = stdcell_m7_strap_pitch_dbu,
                     offset = offset_dbu,
                     number_of_straps = 0,
                     snap = False,
                     starts_with = pdn.GRID,
                     extend = pdn.RINGS, # Extend to connect to the M7 rings
                     nets = []) # Use grid nets

    # M8 straps (typically vertical)
    print("Adding M8 straps to core grid...")
    pdngen.makeStrap(grid = core_grid,
                     layer = m8,
                     width = stdcell_m8_strap_width_dbu,
                     spacing = stdcell_m8_strap_spacing_dbu,
                     pitch = stdcell_m8_strap_pitch_dbu,
                     offset = offset_dbu,
                     number_of_straps = 0,
                     snap = False,
                     starts_with = pdn.GRID,
                     extend = pdn.RINGS, # Extend to connect to the M8 rings (or BOUNDARY if no M8 rings)
                     nets = []) # Use grid nets

    # Add connects between layers for the core grid
    # M1 to M4, M4 to M7, M7 to M8
    print("Adding connects between core grid layers (M1-M4, M4-M7, M7-M8)...")
    # cut_pitch_x/y = 0 means use default via spacing/geometry from tech file
    pdngen.makeConnect(grid = core_grid, layer0 = m1, layer1 = m4,
                       cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu) # Assumes M1 is Horizontal, M4 is Vertical
    pdngen.makeConnect(grid = core_grid, layer0 = m4, layer1 = m7,
                       cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu) # Assumes M4 is Vertical, M7 is Horizontal
    pdngen.makeConnect(grid = core_grid, layer0 = m7, layer1 = m8,
                       cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu) # Assumes M7 is Horizontal, M8 is Vertical
else:
    print("Warning: Core grid not found after creation attempt. Skipping core PDN config.")


# Create power grid for macro blocks (Instance Grids) - Only if macros exist
if len(macros) > 0:
    print(f"Creating Instance PDN Grids for {len(macros)} macros...")
    # Halo for instance grid defines how far from macro boundary the grid extends/connects
    # Re-using the placement halo value as a reasonable default for PDN halo
    macro_pdn_halo_um = macro_halo_width_um # Assuming square halo
    macro_pdn_halo_dbu = design.micronToDBU(macro_pdn_halo_um)

    for i, macro in enumerate(macros):
        print(f"Configuring PDN for macro instance: {macro.getName()}...")
        # Create separate instance grid for each macro
        macro_instance_grid_name = f"macro_grid_{macro.getName()}"
        pdngen.makeInstanceGrid(domain = core_domain, # Macros are typically in the core domain
                                name = macro_instance_grid_name, # Use macro name for unique grid name
                                starts_with = pdn.GROUND, # Match core grid pattern
                                inst = macro, # Associate grid with this specific instance
                                halo = [macro_pdn_halo_dbu]*4, # Halo around the macro instance boundary
                                pg_pins_to_boundary = True,  # Connect macro PG pins to the grid boundary/halo
                                default_grid = False, # Not a default grid for the domain
                                # generate_obstructions, is_bump not specified
                                )

        macro_instance_grid = pdngen.findGrid(macro_instance_grid_name)
        if macro_instance_grid is not None:
            # Add rings on M5 and M6 around the macro instance boundary
            print("Adding M5/M6 rings to macro instance grid around macro boundary...")
            pdngen.makeRing(grid = macro_instance_grid,
                            layer0 = m5, width0 = macro_ring_width_dbu, spacing0 = macro_ring_spacing_dbu,
                            layer1 = m6, width1 = macro_ring_width_dbu, spacing1 = macro_ring_spacing_dbu,
                            starts_with = pdn.GRID, # Match grid pattern
                            offset = [offset_dbu]*4, # 0 offset from macro instance boundary
                            pad_offset = [offset_dbu]*4, # 0 pad offset
                            extend = False, # Rings stay within the instance grid boundary/halo
                            pad_pin_layers = [], # No connection to pads specified
                            nets = []) # Use grid nets (VDD/VSS)

            # Add strap patterns on M5 and M6 inside the macro instance grid/halo area
            # M5 straps
            print("Adding M5 straps to macro instance grid...")
            pdngen.makeStrap(grid = macro_instance_grid,
                             layer = m5,
                             width = macro_strap_width_dbu,
                             spacing = macro_strap_spacing_dbu,
                             pitch = macro_strap_pitch_dbu,
                             offset = offset_dbu,
                             number_of_straps = 0,
                             snap = True, # Snap straps to grid/track if possible inside macro area
                             starts_with = pdn.GRID,
                             extend = pdn.RINGS, # Extend to connect to the M5 rings
                             nets = []) # Use grid nets

            # M6 straps
            print("Adding M6 straps to macro instance grid...")
            pdngen.makeStrap(grid = macro_instance_grid,
                             layer = m6,
                             width = macro_strap_width_dbu,
                             spacing = macro_strap_spacing_dbu,
                             pitch = macro_strap_pitch_dbu,
                             offset = offset_dbu,
                             number_of_straps = 0,
                             snap = True,
                             starts_with = pdn.GRID,
                             extend = pdn.RINGS, # Extend to connect to the M6 rings
                             nets = []) # Use grid nets

            # Add connects between layers for the macro instance grid and to core grid layers
            # Connect macro grid (M5, M6) to core grid layers (M4, M7) as specified implicitly by the overall structure (M4 core, M5/M6 macro, M7 core)
            # M4 (core) to M5 (macro) connect
            print("Adding connects between macro/core PDN layers (M4-M5, M5-M6, M6-M7)...")
            pdngen.makeConnect(grid = macro_instance_grid, layer0 = m4, layer1 = m5,
                               cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu) # Assumes M4 V, M5 H
            # M5 to M6 (macro layers) connect
            pdngen.makeConnect(grid = macro_instance_grid, layer0 = m5, layer1 = m6,
                               cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu) # Assumes M5 H, M6 V
            # M6 (macro) to M7 (core) connect
            pdngen.makeConnect(grid = macro_instance_grid, layer0 = m6, layer1 = m7,
                               cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu) # Assumes M6 V, M7 H

        else:
            print(f"Warning: Macro instance grid for '{macro.getName()}' not found after creation attempt. Skipping macro PDN config for this instance.")
else:
    print("No macros found. Skipping macro PDN configuration.")


# Verify power grid setup
print("Checking PDN setup...")
pdngen.checkSetup()
# Build the power grid shapes but do not route yet (False)
print("Building PDN shapes...")
# The 'buildGrids' call processes all configured grids and creates the geometric shapes in memory.
# The 'writeToDb' call writes these shapes to the design database.
pdngen.buildGrids(False) # False means do not attempt to route yet
# Write the generated power grid shapes to the design database
print("Writing PDN shapes to DB...")
pdngen.writeToDb(True) # True means write the shapes
# Reset temporary shapes used during generation
pdngen.resetShapes()
print("PDN construction finished.")


# --- 9. Routing ---
print("--- Starting Routing Stages ---")

# Configure and run global routing
grt = design.getGlobalRouter()

# Get routing layer levels
# Ensure metal layers exist before getting levels (checked during PDN setup)
min_routing_layer_obj = db.getTech().findLayer("metal1")
max_routing_layer_obj = db.getTech().findLayer("metal7")

if min_routing_layer_obj is None or max_routing_layer_obj is None:
     print("Error: Specified routing layers (metal1 or metal7) not found in tech. Cannot proceed with routing.")
     exit(1) # Exit on critical error

min_routing_layer = min_routing_layer_obj.getRoutingLevel()
max_routing_layer = max_routing_layer_obj.getRoutingLevel()

print(f"Setting global routing layers from {min_routing_layer_obj.getName()} (Level {min_routing_layer}) to {max_routing_layer_obj.getName()} (Level {max_routing_layer})")
grt.setMinRoutingLayer(min_routing_layer)
grt.setMaxRoutingLayer(max_routing_layer)
# Route clocks on same layers as signals unless specified otherwise
grt.setMinLayerForClock(min_routing_layer)
grt.setMaxLayerForClock(max_routing_layer)

# The prompt mentioned 30 iterations for "global router", likely intended for global placer.
# Standard global router does not have a simple iteration count parameter like that.
# Using common global router parameters.
# grt.setAdjustment(0.5) # Example adjustment value for congestion
grt.setVerbose(True)
# grt.setCubicCongestionPenalty(1.0) # Example penalty

# Run global routing (True means to route)
print("Running Global Routing...")
grt.globalRoute(True)
print("Global Routing finished.")


# Configure and run detailed routing
drter = design.getTritonRoute()
dr_params = drt.ParamStruct()

# Set routing layer range for detailed router
dr_params.bottomRoutingLayer = min_routing_layer_obj.getName()
dr_params.topRoutingLayer = max_routing_layer_obj.getName()
print(f"Setting detailed routing layers from {dr_params.bottomRoutingLayer} to {dr_params.topRoutingLayer}")

# Configure other detailed router parameters (using defaults or common settings)
dr_params.outputMazeFile = ""
dr_params.outputDrcFile = "route_drc.rpt" # Output DRC report file name
dr_params.outputCmapFile = ""
dr_params.outputGuideCoverageFile = ""
dr_params.dbProcessNode = "" # Leave empty unless process node is needed/specified
dr_params.enableViaGen = True # Allow via generation
dr_params.drouteEndIter = 1 # Number of detailed routing iterations (1 is common for initial pass, more for fixing)
dr_params.viaInPinBottomLayer = "" # Optional: specify layer for via-in-pin if allowed by tech
dr_params.viaInPinTopLayer = "" # Optional: specify layer for via-in-pin
dr_params.orSeed = -1 # Random seed (-1 means use time)
dr_params.orK = 0 # K factor for random placement (usually 0 for non-random)
dr_params.verbose = 1 # Verbose output level
dr_params.cleanPatches = True # Clean up routing patches
dr_params.doPa = True # Perform post-route antenna fixing
dr_params.singleStepDR = False # Do not run in single step mode
dr_params.minAccessPoints = 1 # Minimum access points for pins
dr_params.saveGuideUpdates = False # Do not save guide updates

drter.setParams(dr_params)
# Run detailed routing
print("Running Detailed Routing...")
drter.main()
print("Detailed Routing finished.")


# --- 10. Final Outputs and Analysis ---
print("--- Generating Outputs and Performing Analysis ---")

# 1. Save final design to DEF
def_output_path = "final.def"
print(f"Saving final design to DEF: {def_output_path}")
design.writeDef(def_output_path)

# 2. Save final netlist to Verilog
verilog_output_path = "final.v"
print(f"Saving final netlist to Verilog: {verilog_output_path}")
design.writeVerilog(verilog_output_path)

# 3. Save final ODB database
odb_output_path = "final.odb"
print(f"Saving final ODB database: {odb_output_path}")
db.save(odb_output_path)

# 4. Perform static IR drop analysis
print("Performing static IR drop analysis...")
power_decap_tool = design.getPowerDecap() # Get the PowerDecap tool

# Ensure VDD net exists (checked during PDN setup)
if VDD_net is None:
    print("Error: VDD net not found for IR drop analysis.")
else:
    # Configure and run static IR drop analysis on VDD
    # The command is typically 'analyze_power' with options for static/dynamic and IR drop
    # The PowerDecap tool's Python API might mirror Tcl commands or have specific methods.
    # Using evalTclString for 'analyze_power' is robust as it matches the command line tool.
    ir_drop_report_path = "static_ir_drop.rpt"
    print(f"Running static IR drop analysis on VDD net, output to {ir_drop_report_path}")
    # Basic static IR drop analysis command example
    # The exact syntax might vary slightly depending on OpenROAD version and features enabled.
    # Assuming analyze_power exists and takes these arguments via Tcl.
    # -net specifies the net(s) to analyze
    # -static enables static analysis mode
    # -ir_drop enables IR drop calculation
    # -outfile specifies the report output file
    design.evalTclString(f"analyze_power -net {{{VDD_net.getName()}}} -static -ir_drop -outfile {ir_drop_report_path}")
    print("Static IR drop analysis finished.")


# 5. Report power consumption
print("Reporting power consumption...")
# This typically requires Static Timing Analysis (STA) setup and power libraries (usually part of Liberty).
sta_tool = design.getTCLpsta() # Get the STA tool instance

# Load necessary power libraries (should be handled by readLiberty earlier)
# Set operating conditions, parasitics, etc. (not specified in prompt, using defaults)
# A minimal STA setup for power involves associating the design with the tool
sta_tool.setBlock(design.getBlock())
# Link the design again within STA context if needed (often done automatically)
# sta_tool.linkDesign(design_top_module_name) # May or may not be necessary depending on API state

# Prime the STA engine (e.g., load parasitics if not already loaded)
# Parasitics should have been loaded during routing.
# sta_tool.readParasitics() # This would typically read SPEF/DSPF after routing

# Set up timing corners (if multiple corners exist) - not specified, using default
# sta_tool.setCurrentCorner(corner) # Example

# Report power
power_report_path = "power_report.rpt"
print(f"Running power report, output to {power_report_path}")
# The report_power command in STA tool reports various power components.
# Using evalTclString for 'report_power' is standard.
# -verbose provides more details, -outfile redirects output.
design.evalTclString(f"report_power -outfile {power_report_path}")
print("Power reporting finished.")


# --- End of Script ---
print("--- Script finished ---")