# Import necessary OpenROAD modules
from openroad import Tech, Design, Timing
from pathlib import Path
import odb
import pdn
import drt
import mpl # MacroPlacer

# --- Configuration ---
# Set paths to library and design files (replace with your actual paths)
# Example: Assuming standard directory structure relative to the script
libDir = Path("../../../library/nangate45/lib")
lefDir = Path("../../../library/nangate45/lef")
techlefDir = Path("../../../library/nangate45/lef") # Often tech LEF is separate or named specifically
designDir = Path("../") # Directory containing your Verilog netlist

# Replace with your actual design name and top module name
design_name = "my_design"
design_top_module_name = "top"

# Clock configuration
clock_port_name = "clk"
clock_name = "core_clock"
clock_period_ns = 40

# Floorplan configuration
die_lx_um = 0
die_ly_um = 0
die_ux_um = 45
die_uy_um = 45
core_lx_um = 5
core_ly_um = 5
core_ux_um = 40
core_uy_um = 40
site_name = "FreePDK45_38x28_10R_NP_162NW_34O" # Replace with your standard cell site name

# Placement configuration
macro_fence_lx_um = 5
macro_fence_ly_um = 5
macro_fence_ux_um = 20
macro_fence_uy_um = 25
macro_halo_um = 5
macro_min_spacing_um = 5 # Minimum distance between macros
global_placement_iterations = 30
detailed_placement_max_disp_x_um = 1
detailed_placement_max_disp_y_um = 3

# CTS configuration
cts_buffer_cell = "BUF_X2" # Name of the buffer cell to use for CTS
wire_rc_resistance = 0.03574 # Unit resistance for RC extraction
wire_rc_capacitance = 0.07516 # Unit capacitance for RC extraction

# PDN Configuration
pdn_via_cut_pitch_um = 0
pdn_offset_um = 0 # Offset for straps and rings

# Standard cell grid config
stdcell_ring_m7_width_um = 5
stdcell_ring_m7_spacing_um = 5
stdcell_ring_m8_width_um = 5
stdcell_ring_m8_spacing_um = 5

stdcell_strap_m1_width_um = 0.07
stdcell_strap_m4_width_um = 1.2
stdcell_strap_m4_spacing_um = 1.2
stdcell_strap_m4_pitch_um = 6
stdcell_strap_m7_width_um = 1.4
stdcell_strap_m7_spacing_um = 1.4
stdcell_strap_m7_pitch_um = 10.8
stdcell_strap_m8_width_um = 1.4
stdcell_strap_m8_spacing_um = 1.4
stdcell_strap_m8_pitch_um = 10.8

# Macro grid config (if macros exist)
macro_ring_m5_width_um = 1.5
macro_ring_m5_spacing_um = 1.5
macro_ring_m6_width_um = 1.5
macro_ring_m6_spacing_um = 1.5

macro_strap_m5_width_um = 1.2
macro_strap_m5_spacing_um = 1.2
macro_strap_m5_pitch_um = 6
macro_strap_m6_width_um = 1.2
macro_strap_m6_spacing_um = 1.2
macro_strap_m6_pitch_um = 6
macro_pdn_halo_um = 0 # Halo around macros for the standard cell PDN grid (default 0)

# Routing configuration
global_routing_min_layer_name = "metal1"
global_routing_max_layer_name = "metal7"
detailed_routing_min_layer_name = "metal1"
detailed_routing_max_layer_name = "metal7"

# Filler configuration
filler_cells_prefix = "FILLCELL_" # Adjust if your library uses a different prefix

# --- OpenROAD Flow ---

# Initialize OpenROAD objects and read technology files
tech = Tech()

# Read all liberty (.lib) and LEF files from the library directories
libFiles = libDir.glob("*.lib")
techLefFiles = techlefDir.glob("*.tech.lef") # Explicitly get technology LEF
cellLefFiles = lefDir.glob('*.lef') # Get cell LEF

# Load liberty timing libraries
for libFile in libFiles:
    tech.readLiberty(libFile.as_posix())

# Load technology and cell LEF files
# Read tech LEF first as it defines layers, sites, etc.
for techLefFile in techLefFiles:
    tech.readLef(techLefFile.as_posix())
# Read cell LEF files
for cellLefFile in cellLefFiles:
    tech.readLef(cellLefFile.as_posix())

# Create design and read Verilog netlist
design = Design(tech)
verilogFile = designDir / f"{design_name}.v"
design.readVerilog(verilogFile.as_posix())

# Link the design to resolve cell masters and nets
# This connects instances to their masters and nets to pins
design.link(design_top_module_name)

# Configure clock constraints
# Create clock signal with specified period on the specified port
# API call: openroad.Design.evalTclString("create_clock -period <period> [get_ports <port>] -name <name>")
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")

# Set the created clock as propagated for timing analysis
# API call: openroad.Design.evalTclString("set_propagated_clock [get_clocks {<clock_name>}]")
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Initialize floorplan
floorplan = design.getFloorplan()

# Set die area using DBU units
# API call: odb.Rect(llx_dbu, lly_dbu, urx_dbu, ury_dbu)
die_area = odb.Rect(design.micronToDBU(die_lx_um), design.micronToDBU(die_ly_um),
    design.micronToDBU(die_ux_um), design.micronToDBU(die_uy_um))

# Set core area using DBU units
# API call: odb.Rect(llx_dbu, lly_dbu, urx_dbu, ury_dbu)
core_area = odb.Rect(design.micronToDBU(core_lx_um), design.micronToDBU(core_ly_um),
    design.micronToDBU(core_ux_um), design.micronToDBU(core_uy_um))

# Find the standard cell site by name
site = floorplan.findSite(site_name)
if not site:
    print(f"[ERROR] Site '{site_name}' not found. Exiting.")
    exit(1)

# Initialize floorplan with defined die/core areas and standard cell site
# API call: floorplan.initFloorplan(die_area, core_area, site)
floorplan.initFloorplan(die_area, core_area, site)

# Create routing tracks based on the standard cell site and routing grid
# API call: floorplan.makeTracks()
floorplan.makeTracks()

# Place macro blocks if present
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
if len(macros) > 0:
    print(f"[INFO] Found {len(macros)} macro instances. Running macro placement.")
    mpl = design.getMacroPlacer()
    block = design.getBlock()

    # Set macro placement parameters
    mpl_params = {
        "num_threads": 64, # Number of threads to use
        "max_num_macro": len(macros), # Consider all macros
        "min_dist_x": design.micronToDBU(macro_min_spacing_um), # Minimum distance between macros in X (DBU)
        "min_dist_y": design.micronToDBU(macro_min_spacing_um), # Minimum distance between macros in Y (DBU)
        "halo_width": design.micronToDBU(macro_halo_um), # Halo around macros (DBU)
        "halo_height": design.micronToDBU(macro_halo_um), # Halo around macros (DBU)
        # Set the fence region for macros (DBU)
        "fence_lx": design.micronToDBU(macro_fence_lx_um),
        "fence_ly": design.micronToDBU(macro_fence_ly_um),
        "fence_ux": design.micronToDBU(macro_fence_ux_um),
        "fence_uy": design.micronToDBU(macro_fence_uy_um),
        # Other parameters can be default or tuned for better results
        "area_weight": 0.5,
        "outline_weight": 100.0,
        "wirelength_weight": 100.0,
        "guidance_weight": 10.0,
        "fence_weight": 10.0,
        "boundary_weight": 50.0,
        "notch_weight": 10.0,
        "macro_blockage_weight": 10.0,
        "pin_access_th": 0.0,
        "target_util": 0.5, # Target utilization inside fence
        "target_dead_space": 0.05,
        "min_ar": 0.33,
        "snap_layer": 4, # Example layer index to snap pins to (adjust if needed)
        "bus_planning_flag": False,
        "report_directory": ""
    }

    # Run macro placement using the configured parameters
    # API call: mpl.MacroPlacer.place(...)
    mpl.place(**mpl_params)
else:
    print("[INFO] No macro instances found. Skipping macro placement.")


# Configure and run global placement
gpl = design.getReplace()

# Disable timing-driven placement for initial stages if timing not stable yet
gpl.setTimingDrivenMode(False)
# Enable routability-driven placement
gpl.setRoutabilityDrivenMode(True)
# Use uniform target density across the core area
gpl.setUniformTargetDensityMode(True)

# Set initial placement iterations
gpl.setInitialPlaceMaxIter(global_placement_iterations)
# Set density penalty factor for initial placement
gpl.setInitDensityPenalityFactor(0.05)

# Perform initial placement phase
# API call: gpl.doInitialPlace(threads=...)
gpl.doInitialPlace(threads = 4) # Adjust thread count as needed

# Perform Nesterov placement phase
# API call: gpl.doNesterovPlace(threads=...)
gpl.doNesterovPlace(threads = 4) # Adjust thread count as needed

# Reset global placer after use
# API call: gpl.reset()
gpl.reset()

# Run initial detailed placement (before CTS)
# Detailed placement helps clean up site placement after global placement
site = design.getBlock().getRows()[0].getSite()
# Convert maximum displacement from um to DBU
max_disp_x_dbu = design.micronToDBU(detailed_placement_max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(detailed_placement_max_disp_y_um)

# Remove potential filler cells before detailed placement (they will be re-inserted later)
design.getOpendp().removeFillers()

# Perform detailed placement with specified max displacement in DBU
# API call: opendp.detailedPlacement(max_displ_x_dbu, max_displ_y_dbu, ...)
design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)


# Configure and run clock tree synthesis (CTS)
# Get the CTS tool handle
# API call: openroad.Design.getTritonCts()
cts = design.getTritonCts()
parms = cts.getParms()
parms.setWireSegmentUnit(20) # Example wire segment unit, adjust as needed

# Set available clock buffers from the library by cell name
# API call: cts.TritonCTS.setBufferList(buffer_names)
cts.setBufferList(cts_buffer_cell)
# Set root buffer (buffer used at the clock source)
# API call: cts.TritonCTS.setRootBuffer(buffer_name)
cts.setRootBuffer(cts_buffer_cell)
# Set sink buffer (buffer used near clock sinks)
# API call: cts.TritonCTS.setSinkBuffer(buffer_name)
cts.setSinkBuffer(cts_buffer_cell)

# Set RC values for clock and signal nets for timing analysis (important for CTS)
# API call: openroad.Design.evalTclString("set_wire_rc -clock -resistance <R> -capacitance <C>")
design.evalTclString(f"set_wire_rc -clock -resistance {wire_rc_resistance} -capacitance {wire_rc_capacitance}")
# API call: openroad.Design.evalTclString("set_wire_rc -signal -resistance <R> -capacitance <C>")
design.evalTclString(f"set_wire_rc -signal -resistance {wire_rc_resistance} -capacitance {wire_rc_capacitance}")

# Run CTS
# API call: cts.TritonCTS.runTritonCts()
cts.runTritonCts()

# After CTS, the design is modified (buffers inserted, potentially moved).
# Perform final detailed placement to clean up placement after CTS.
site = design.getBlock().getRows()[0].getSite()
# Convert maximum displacement from um to DBU
max_disp_x_dbu = design.micronToDBU(detailed_placement_max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(detailed_placement_max_disp_y_um)

# Perform detailed placement again
# API call: opendp.detailedPlacement(max_displ_x_dbu, max_displ_y_dbu, ...)
design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)


# Insert filler cells to fill empty spaces and connect disconnected standard cell power/ground pins
db = design.getTech().getDB()
filler_masters = list()
# Find filler cell masters in the library based on type (CORE_SPACER)
for lib in db.getLibs():
    for master in lib.getMasters():
        # Check if the master is a core spacer (filler cell)
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

# Perform filler placement if filler cells are found
if len(filler_masters) == 0:
    print("[WARNING] No CORE_SPACER cells found in library. Skipping filler placement.")
else:
    print(f"[INFO] Found {len(filler_masters)} filler cell types. Running filler placement.")
    # API call: opendp.fillerPlacement(filler_masters, prefix, verbose)
    design.getOpendp().fillerPlacement(filler_masters = filler_masters,
                                     prefix = filler_cells_prefix,
                                     verbose = False)


# Configure and build Power Delivery Network (PDN)
# Get the PDN generator tool handle
pdngen = design.getPdnGen()

# Set up global power/ground connections
# Iterate through all nets in the block
for net in design.getBlock().getNets():
    # Check if the net is a power or ground net based on signal type
    if net.getSigType() == "POWER" or net.getSigType() == "GROUND":
        # Mark power/ground nets as special nets (prevents routing tools from ripping them up)
        # API call: odb.dbNet.setSpecial()
        net.setSpecial()

# Find existing power and ground nets by name
VDD_net = design.getBlock().findNet("VDD") # Replace with your actual power net name
VSS_net = design.getBlock().findNet("VSS") # Replace with your actual ground net name
switched_power = None # Define if you have switched power domains
secondary_nets = list() # Define if you have secondary power/ground nets

# Create VDD/VSS nets if they were not found (e.g., if not in Verilog netlist)
if VDD_net is None:
    VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
    # API call: odb.dbNet.setSigType(type_string)
    VDD_net.setSigType("POWER")
    VDD_net.setSpecial()
if VSS_net is None:
    VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
    VSS_net.setSigType("GROUND")
    VSS_net.setSpecial()

# Connect standard cell power/ground pins to the global nets
# Connect all VDD pins to the VDD net for all instances in the design
design.getBlock().addGlobalConnect(region = None,
    instPattern = ".*", # Apply to all instances
    pinPattern = "^VDD$", # Apply to pins named VDD (adjust pattern if needed)
    net = VDD_net,
    do_connect = True)
# Connect all VSS pins to the VSS net for all instances in the design
design.getBlock().addGlobalConnect(region = None,
    instPattern = ".*", # Apply to all instances
    pinPattern = "^VSS$", # Apply to pins named VSS (adjust pattern if needed)
    net = VSS_net,
    do_connect = True)
# Apply the global connections to the design database
design.getBlock().globalConnect()

# Configure the core power domain
# Assign the primary power and ground nets to the core domain
# API call: pdn.PdnGen.setCoreDomain(power_net, switched_power_net, ground_net, secondary_net_list)
pdngen.setCoreDomain(power = VDD_net,
    switched_power = switched_power,
    ground = VSS_net,
    secondary = secondary_nets)

# Define domains for grid generation (usually just the Core domain)
domains = [pdngen.findDomain("Core")]
if not domains:
    print("[ERROR] Core domain not found. Cannot build PDN. Exiting.")
    exit(1)


# Define halo around macros for the standard cell power grid (used to exclude standard cell PDN from macro areas)
# Use 0 as per example/no specific instruction for PDN halo
stdcell_grid_halo_dbu = [design.micronToDBU(macro_pdn_halo_um) for i in range(4)]

# Create the main core power grid structure definition for standard cells
for domain in domains:
    # API call: pdn.PdnGen.makeCoreGrid(...)
    pdngen.makeCoreGrid(domain = domain,
    name = "stdcell_grid", # Name for the standard cell grid definition
    starts_with = pdn.GROUND, # Specify whether grid starts with ground or power
    pin_layers = [], # Pin layers to connect to (usually standard cell power rails)
    generate_obstructions = [], # Layers on which to generate obstructions
    powercell = None, # Power switch cell master if needed
    powercontrol = None, # Power control logic name
    powercontrolnetwork = "STAR") # Power control network type

# Find the created standard cell grid object definition
stdcell_grid = pdngen.findGrid("stdcell_grid")
if not stdcell_grid:
    print("[ERROR] Standard cell grid definition not found. Cannot build PDN. Exiting.")
    exit(1)

# Get routing layer objects by name
m1 = design.getTech().getDB().getTech().findLayer("metal1")
m4 = design.getTech().getDB().getTech().findLayer("metal4")
m5 = design.getTech().getDB().getTech().findLayer("metal5")
m6 = design.getTech().getDB().getTech().findLayer("metal6")
m7 = design.getTech().getDB().getTech().findLayer("metal7")
m8 = design.getTech().getDB().getTech().findLayer("metal8")

# Check if required layers exist
required_layers = [m1, m4, m5, m6, m7, m8]
layer_names = ["metal1", "metal4", "metal5", "metal6", "metal7", "metal8"]
for layer, name in zip(required_layers, layer_names):
    if not layer:
        print(f"[ERROR] Layer '{name}' not found in technology file. Cannot build PDN. Exiting.")
        exit(1)

# Convert PDN dimensions from um to DBU
pdn_via_cut_pitch_dbu = [design.micronToDBU(pdn_via_cut_pitch_um) for i in range(2)] # X and Y pitch
pdn_offset_dbu = [design.micronToDBU(pdn_offset_um) for i in range(4)] # Offset has 4 values (left, bottom, right, top) for makeRing
pdn_strap_offset_dbu = design.micronToDBU(pdn_offset_um) # Offset has 1 value for makeStrap

# Standard cell grid dimensions in DBU
stdcell_ring_m7_width_dbu = design.micronToDBU(stdcell_ring_m7_width_um)
stdcell_ring_m7_spacing_dbu = design.micronToDBU(stdcell_ring_m7_spacing_um)
stdcell_ring_m8_width_dbu = design.micronToDBU(stdcell_ring_m8_width_um)
stdcell_ring_m8_spacing_dbu = design.micronToDBU(stdcell_ring_m8_spacing_um)

stdcell_strap_m1_width_dbu = design.micronToDBU(stdcell_strap_m1_width_um)
stdcell_strap_m4_width_dbu = design.micronToDBU(stdcell_strap_m4_width_um)
stdcell_strap_m4_spacing_dbu = design.micronToDBU(stdcell_strap_m4_spacing_um)
stdcell_strap_m4_pitch_dbu = design.micronToDBU(stdcell_strap_m4_pitch_um)
stdcell_strap_m7_width_dbu = design.micronToDBU(stdcell_strap_m7_width_um)
stdcell_strap_m7_spacing_dbu = design.micronToDBU(stdcell_strap_m7_spacing_um)
stdcell_strap_m7_pitch_dbu = design.micronToDBU(stdcell_strap_m7_pitch_um)
stdcell_strap_m8_width_dbu = design.micronToDBU(stdcell_strap_m8_width_um)
stdcell_strap_m8_spacing_dbu = design.micronToDBU(stdcell_strap_m8_spacing_um)
stdcell_strap_m8_pitch_dbu = design.micronToDBU(stdcell_strap_m8_pitch_um)


# Add rings and straps definitions to the standard cell grid
for g in stdcell_grid:
    # Create power rings around core area on metal7 and metal8
    # API call: pdn.PdnGen.makeRing(...)
    pdngen.makeRing(grid = g,
        layer0 = m7,
        width0 = stdcell_ring_m7_width_dbu,
        spacing0 = stdcell_ring_m7_spacing_dbu,
        layer1 = m8,
        width1 = stdcell_ring_m8_width_dbu,
        spacing1 = stdcell_ring_m8_spacing_dbu,
        starts_with = pdn.GRID, # Rings start according to grid definition (e.g., alternating VDD/VSS)
        offset = pdn_offset_dbu, # Offset from core boundary
        pad_offset = pdn_offset_dbu, # No pad offset specified
        extend = False, # Do not extend the ring beyond its defined area
        pad_pin_layers = [], # Layers to connect to pads (if rings connect to pads)
        nets = []) # Nets to include in the ring (empty means all PG nets in domain)

    # Create horizontal power straps on metal1 (typically for standard cell power rails connection)
    # These follow the pin pattern of standard cells
    # API call: pdn.PdnGen.makeFollowpin(...)
    pdngen.makeFollowpin(grid = g,
        layer = m1,
        width = stdcell_strap_m1_width_dbu,
        extend = pdn.CORE) # Extend straps to the core boundary

    # Create power straps on metal4 with specified width, spacing, and pitch
    # API call: pdn.PdnGen.makeStrap(...)
    pdngen.makeStrap(grid = g,
        layer = m4,
        width = stdcell_strap_m4_width_dbu,
        spacing = stdcell_strap_m4_spacing_dbu,
        pitch = stdcell_strap_m4_pitch_dbu,
        offset = pdn_strap_offset_dbu, # Offset from the start point
        number_of_straps = 0, # Auto-calculate number of straps
        snap = False, # Do not snap to grid lines
        starts_with = pdn.GRID,
        extend = pdn.CORE, # Extend straps to the core boundary
        nets = [])

    # Create power straps on metal7 with specified width, spacing, and pitch
    pdngen.makeStrap(grid = g,
        layer = m7,
        width = stdcell_strap_m7_width_dbu,
        spacing = stdcell_strap_m7_spacing_dbu,
        pitch = stdcell_strap_m7_pitch_dbu,
        offset = pdn_strap_offset_dbu,
        number_of_straps = 0,
        snap = False,
        starts_with = pdn.GRID,
        extend = pdn.RINGS, # Extend straps to connect to the rings on M7/M8
        nets = [])

    # Create power straps on metal8 with specified width, spacing, and pitch
    pdngen.makeStrap(grid = g,
        layer = m8,
        width = stdcell_strap_m8_width_dbu,
        spacing = stdcell_strap_m8_spacing_dbu,
        pitch = stdcell_strap_m8_pitch_dbu,
        offset = pdn_strap_offset_dbu,
        number_of_straps = 0,
        snap = False,
        starts_with = pdn.GRID,
        extend = pdn.RINGS, # Extend straps to connect to the rings on M7/M8
        nets = [])

    # Create via connections between standard cell power grid layers
    # API call: pdn.PdnGen.makeConnect(...)
    # Connect metal1 to metal4
    pdngen.makeConnect(grid = g,
        layer0 = m1,
        layer1 = m4,
        cut_pitch_x = pdn_via_cut_pitch_dbu[0],
        cut_pitch_y = pdn_via_cut_pitch_dbu[1],
        vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
    # Connect metal4 to metal7
    pdngen.makeConnect(grid = g,
        layer0 = m4,
        layer1 = m7,
        cut_pitch_x = pdn_via_cut_pitch_dbu[0],
        cut_pitch_y = pdn_via_cut_pitch_dbu[1],
        vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
    # Connect metal7 to metal8
    pdngen.makeConnect(grid = g,
        layer0 = m7,
        layer1 = m8,
        cut_pitch_x = pdn_via_cut_pitch_dbu[0],
        cut_pitch_y = pdn_via_cut_pitch_dbu[1],
        vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")


# Build power grid for macro blocks if they exist
if len(macros) > 0:
    print("[INFO] Building PDN for macros.")
    # Macro grid dimensions in DBU
    macro_ring_m5_width_dbu = design.micronToDBU(macro_ring_m5_width_um)
    macro_ring_m5_spacing_dbu = design.micronToDBU(macro_ring_m5_spacing_um)
    macro_ring_m6_width_dbu = design.micronToDBU(macro_ring_m6_width_um)
    macro_ring_m6_spacing_dbu = design.micronToDBU(macro_ring_m6_spacing_um)

    macro_strap_m5_width_dbu = design.micronToDBU(macro_strap_m5_width_um)
    macro_strap_m5_spacing_dbu = design.micronToDBU(macro_strap_m5_spacing_um)
    macro_strap_m5_pitch_dbu = design.micronToDBU(macro_strap_m5_pitch_um)
    macro_strap_m6_width_dbu = design.micronToDBU(macro_strap_m6_width_um)
    macro_strap_m6_spacing_dbu = design.micronToDBU(macro_strap_m6_spacing_um)
    macro_strap_m6_pitch_dbu = design.micronToDBU(macro_strap_m6_pitch_um)

    macro_pdn_halo_dbu = [design.micronToDBU(macro_pdn_halo_um) for i in range(4)] # Halo around macro for PDN

    for i, macro in enumerate(macros):
        # Create a separate power grid definition for each macro instance
        # API call: pdn.PdnGen.makeInstanceGrid(...)
        for domain in domains:
            pdngen.makeInstanceGrid(domain = domain,
                name = f"macro_grid_{i}", # Unique name for each macro grid definition
                starts_with = pdn.GROUND, # Can be GRID, POWER, or GROUND
                inst = macro, # The macro instance this grid applies to
                halo = macro_pdn_halo_dbu, # Halo around macro for grid exclusion
                pg_pins_to_boundary = True, # Connect macro PG pins to the grid boundary
                default_grid = False, # Not the default grid for the domain
                generate_obstructions = [],
                is_bump = False)

        grid = pdngen.findGrid(f"macro_grid_{i}") # Find the grid definition for this macro
        if not grid:
             print(f"[WARNING] Macro grid definition for {macro.getName()} not found.")
             continue

        for g in grid:
            # Create power ring around macro using metal5 and metal6
            # API call: pdn.PdnGen.makeRing(...)
            pdngen.makeRing(grid = g,
                layer0 = m5,
                width0 = macro_ring_m5_width_dbu,
                spacing0 = macro_ring_m5_spacing_dbu,
                layer1 = m6,
                width1 = macro_ring_m6_width_dbu,
                spacing1 = macro_ring_m6_spacing_dbu,
                starts_with = pdn.GRID,
                offset = pdn_offset_dbu, # Offset from macro boundary
                pad_offset = pdn_offset_dbu, # No pad offset specified
                extend = False, # Do not extend the ring
                pad_pin_layers = [],
                nets = []) # Empty nets list includes all PG nets in the domain

            # Create power straps on metal5 for macro connections
            # API call: pdn.PdnGen.makeStrap(...)
            pdngen.makeStrap(grid = g,
                layer = m5,
                width = macro_strap_m5_width_dbu,
                spacing = macro_strap_m5_spacing_dbu,
                pitch = macro_strap_m5_pitch_dbu,
                offset = pdn_strap_offset_dbu,
                number_of_straps = 0,
                snap = True, # Snap straps to grid lines
                starts_with = pdn.GRID,
                extend = pdn.RINGS, # Extend straps to connect to the rings on M5/M6
                nets = [])

            # Create power straps on metal6 for macro connections
            pdngen.makeStrap(grid = g,
                layer = m6,
                width = macro_strap_m6_width_dbu,
                spacing = macro_strap_m6_spacing_dbu,
                pitch = macro_strap_m6_pitch_dbu,
                offset = pdn_strap_offset_dbu,
                number_of_straps = 0,
                snap = True, # Snap straps to grid lines
                starts_with = pdn.GRID,
                extend = pdn.RINGS, # Extend straps to connect to the rings on M5/M6
                nets = [])

            # Create via connections between macro power grid layers and potentially core grid layers
            # API call: pdn.PdnGen.makeConnect(...)
            # Connect metal4 (from core grid) to metal5 (macro grid) - assumes M4 is accessible below macro
            pdngen.makeConnect(grid = g,
                layer0 = m4,
                layer1 = m5,
                cut_pitch_x = pdn_via_cut_pitch_dbu[0],
                cut_pitch_y = pdn_via_cut_pitch_dbu[1],
                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
            # Connect metal5 to metal6 (macro grid layers)
            pdngen.makeConnect(grid = g,
                layer0 = m5,
                layer1 = m6,
                cut_pitch_x = pdn_via_cut_pitch_dbu[0],
                cut_pitch_y = pdn_via_cut_pitch_dbu[1],
                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
            # Connect metal6 (macro grid) to metal7 (core grid) - assumes M7 is accessible above macro
            pdngen.makeConnect(grid = g,
                layer0 = m6,
                layer1 = m7,
                cut_pitch_x = pdn_via_cut_pitch_dbu[0],
                cut_pitch_y = pdn_via_cut_pitch_dbu[1],
                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")

# Verify the PDN setup configuration
# API call: pdn.PdnGen.checkSetup()
pdngen.checkSetup()

# Build the power grid shapes in the database based on the definitions
# The argument 'False' indicates not to connect to pads immediately
# API call: pdn.PdnGen.buildGrids(connect_to_pads)
pdngen.buildGrids(False)

# Write the created power grid shapes (rings, straps, vias) to the design database
# The 'True' argument likely relates to connecting to pins
# API call: pdn.PdnGen.writeToDb(connect_to_pins, connect_to_pads)
pdngen.writeToDb(True, ) # Assuming True for connecting to pins, False for pads

# Reset temporary shapes used during generation
# API call: pdn.PdnGen.resetShapes()
pdngen.resetShapes()


# Configure and run global routing
grt = design.getGlobalRouter()

# Get routing layer objects by name
min_groute_layer = design.getTech().getDB().getTech().findLayer(global_routing_min_layer_name)
max_groute_layer = design.getTech().getDB().getTech().findLayer(global_routing_max_layer_name)

if not min_groute_layer or not max_groute_layer:
    print(f"[ERROR] Could not find global routing layers {global_routing_min_layer_name} or {global_routing_max_layer_name}. Exiting.")
    exit(1)

# Set the minimum and maximum routing layers for signal nets by routing level
# API call: grt.GlobalRouter.setMinRoutingLayer(level)
grt.setMinRoutingLayer(min_groute_layer.getRoutingLevel())
# API call: grt.GlobalRouter.setMaxRoutingLayer(level)
grt.setMaxRoutingLayer(max_groute_layer.getRoutingLevel())

# Set the minimum and maximum routing layers for clock nets (often same as signal unless special layers are used)
# Prompt did not specify separate clock routing layers, use the same range
# API call: grt.GlobalRouter.setMinLayerForClock(level)
grt.setMinLayerForClock(min_groute_layer.getRoutingLevel())
# API call: grt.GlobalRouter.setMaxLayerForClock(level)
grt.setMaxLayerForClock(max_groute_layer.getRoutingLevel())

# Set congestion adjustment factor (lower values reduce congestion, may increase wirelength)
grt.setAdjustment(0.5) # Example value, tune based on design/process

# Enable verbose output for global routing
grt.setVerbose(True)

# Run global routing
# The 'True' argument typically enables congestion-driven routing
# API call: grt.GlobalRouter.globalRoute(congestion_driven)
grt.globalRoute(True)

# Save the design state after global routing (e.g., to DEF for visualization)
# This is a good practice to check the global route result
design.writeDef("post_global_route.def")


# Configure and run detailed routing
drter = design.getTritonRoute()
params = drt.ParamStruct()

# Set routing layer range for detailed routing by layer name
params.bottomRoutingLayer = detailed_routing_min_layer_name
params.topRoutingLayer = detailed_routing_max_layer_name

# Set other detailed routing parameters
params.outputMazeFile = ""
params.outputDrcFile = "detailed_route.drc" # Specify a file name to get a DRC report
params.outputCmapFile = ""
params.outputGuideCoverageFile = ""
params.dbProcessNode = "" # Process node if applicable
params.enableViaGen = True # Enable via generation
params.drouteEndIter = 1 # Number of detailed routing iterations
params.viaInPinBottomLayer = "" # Optionally restrict via-in-pin layers by name
params.viaInPinTopLayer = "" # Optionally restrict via-in-pin layers by name
params.orSeed = -1 # Obstruction removal random seed (-1 for auto)
params.orK = 0 # Obstruction removal parameter
params.verbose = 1 # Verbosity level (0-3)
params.cleanPatches = True # Clean small routing patches
params.doPa = True # Enable pin access (connecting instances to grid)
params.singleStepDR = False # Run detailed routing in a single step
params.minAccessPoints = 1 # Minimum access points for pin connections
params.saveGuideUpdates = False # Save guide updates

# Set the detailed routing parameters in the tool
# API call: drter.setParams(params_struct)
drter.setParams(params)

# Run detailed routing
# API call: drter.main()
drter.main()

# Save final design outputs
# Write final DEF file
design.writeDef("final.def")

# Write final Verilog netlist (post-CTS, post-filler, post-routing)
design.evalTclString("write_verilog final.v")

# Optional: Run timing analysis after routing if desired
# timing = Timing(design)
# timing.reportTiming(timing.getCorners()[0]) # Report timing for the first corner
# timing.reportPower() # Report power if power models are available

print("[INFO] OpenROAD flow script finished.")