from openroad import Tech, Design, Timing
from pathlib import Path
import pdn, odb, drt, psm
import openroad as ord

# --- File Paths and Design Setup ---
# Set paths to library and design files
# IMPORTANT: Replace these placeholder paths and names with your actual file locations and top module name.
lib_dir = Path("../libs/lib") # Example: Path to directory containing .lib files
lef_dir = Path("../tech/lef") # Example: Path to directory containing .lef files
design_dir = Path("../designs/") # Example: Path to directory containing Verilog file
verilog_file = design_dir / "my_design.v" # Example: Replace with your Verilog file name (netlist)
top_module_name = "my_design" # Example: Replace with your top module name
clock_port_name = "clk" # Replace with your clock port name
site_name = "Your_Site_Name" # Replace with a valid site name from your LEF files

# Initialize OpenROAD objects and read technology files
tech = Tech()

# Read all liberty (.lib) and LEF files from the library directories
lib_files = lib_dir.glob("*.lib")
lef_files = lef_dir.glob('*.lef')

# Load liberty timing libraries
print("Reading liberty files...")
for lib_file in lib_files:
    tech.readLiberty(lib_file.as_posix())
# Load LEF files (technology and cell LEF)
print("Reading LEF files...")
for lef_file in lef_files:
    tech.readLef(lef_file.as_posix())

# Create design and read Verilog netlist
design = Design(tech)
# Read the Verilog design netlist
print(f"Reading Verilog file: {verilog_file}...")
design.readVerilog(verilog_file.as_posix())
# Link the design modules
print(f"Linking design: {top_module_name}...")
design.link(top_module_name)

# --- Clock Setup ---
# Define clock period in nanoseconds
clock_period_ns = 40
# Create clock signal on the specified port using Tcl command
print(f"Setting up clock: period {clock_period_ns} ns on port {clock_port_name}...")
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name core_clock")
# Propagate the clock signal using Tcl command
design.evalTclString("set_propagated_clock [get_clocks {core_clock}]")

# --- Floorplanning ---
print("Starting floorplanning...")
floorplan = design.getFloorplan()
# Find the core site defined in the LEF file
site = floorplan.findSite(site_name)
if not site:
    print(f"Error: Site '{site_name}' not found in LEF files. Please check your LEF and the site_name variable.")
    exit()

# Define floorplan parameters
utilization = 0.45
aspect_ratio = 1.0 # Assuming square shape as default if not specified otherwise
core_to_die_spacing_um = 5.0
spacing_dbu = design.micronToDBU(core_to_die_spacing_um)

# Initialize floorplan with core and die area based on utilization and spacing
floorplan.initFloorplan(utilization, aspect_ratio, spacing_dbu, spacing_dbu, spacing_dbu, spacing_dbu, site)
# Make routing tracks within the floorplan
floorplan.makeTracks()
print("Floorplanning completed.")

# --- IO Placement ---
print("Starting IO placement...")
io_placer = design.getIOPlacer()
io_placer_params = io_placer.getParameters()
io_placer_params.setRandSeed(42) # Use a fixed seed for reproducibility
io_placer_params.setMinDistanceInTracks(False)
io_placer_params.setMinDistance(design.micronToDBU(0)) # No minimum distance between pins specified
io_placer_params.setCornerAvoidance(design.micronToDBU(0)) # No corner avoidance specified

# Find metal layers for IO placement (M8 horizontal, M9 vertical)
metal8 = design.getTech().getDB().getTech().findLayer("metal8")
metal9 = design.getTech().getDB().getTech().findLayer("metal9")

if not metal8 or not metal9:
     print("Error: Metal layers metal8 or metal9 not found. Please check your LEF.")
     exit()

# Add specified layers for horizontal and vertical pin placement
io_placer.addHorLayer(metal8)
io_placer.addVerLayer(metal9)
# Run I/O placement using annealing algorithm
io_placer.runAnnealing(True) # True enables random mode
print("IO placement completed.")

# --- Placement ---
print("Starting placement...")
# Get block object to access design elements
block = design.getBlock()
# Get core area dimensions
core_area = block.getCoreArea()

# Find macro instances in the design
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

# Macro Placement (if macros exist)
if len(macros) > 0:
    print(f"Found {len(macros)} macros. Running macro placement...")
    macro_placer = design.getMacroPlacer()
    # Define macro placement parameters
    macro_halo_um = 5.0
    # Note: Direct parameter for minimum distance *between* macros is not
    # available in the provided API example. The halo and fence help guide
    # placement, and detailed placement will resolve any remaining overlaps
    # or DRC issues based on library definitions.
    macro_placer.place(
        num_threads = 64, # Adjust thread count for performance
        halo_width = macro_halo_um,
        halo_height = macro_halo_um,
        fence_lx = block.dbuToMicrons(core_area.xMin()), # Fence region set to core area
        fence_ly = block.dbuToMicrons(core_area.yMin()),
        fence_ux = block.dbuToMicrons(core_area.xMax()),
        fence_uy = block.dbuToMicrons(core_area.yMax()),
        # Using default weights and parameters from example where not specified otherwise
        area_weight = 0.1, outline_weight = 100.0, wirelength_weight = 100.0, guidance_weight = 10.0,
        fence_weight = 10.0, boundary_weight = 50.0, notch_weight = 10.0, macro_blockage_weight = 10.0,
        pin_access_th = 0.0, target_util = 0.25, target_dead_space = 0.05, min_ar = 0.33,
        snap_layer = 4, # Assuming snapping to layer 4 tracks for macro pins as in example
        bus_planning_flag = False, report_directory = ""
    )
    print("Macro placement completed.")
else:
    print("No macros found in the design. Skipping macro placement.")


# Global Placement for standard cells
print("Starting global placement...")
global_placer = design.getReplace()
global_placer.setTimingDrivenMode(False) # Disable timing-driven mode for simplicity (can enable if timing is good)
global_placer.setRoutabilityDrivenMode(True) # Enable routability-driven mode
global_placer.setUniformTargetDensityMode(True) # Use uniform target density
# Set global placement iterations
global_placer.setInitialPlaceMaxIter(30) # Set max iterations for initial placement
global_placer.setInitDensityPenalityFactor(0.05) # Initial density penalty factor
# Run initial placement
global_placer.doInitialPlace(threads = 4) # Adjust thread count
# Run Nesterov placement
global_placer.doNesterovPlace(threads = 4) # Adjust thread count
global_placer.reset() # Reset global placer state

# Detailed Placement (Initial)
print("Starting initial detailed placement...")
detailed_placer = design.getOpendp()
# Define maximum displacement in microns
max_disp_x_um = 1.0
max_disp_y_um = 3.0
# Get site dimensions to convert micron displacement to site displacement units
site = block.getRows()[0].getSite()
site_width = site.getWidth()
site_height = site.getHeight()
# Calculate max displacement in DBU, then convert to site units
max_disp_x_site = int(design.micronToDBU(max_disp_x_um) / site_width)
max_disp_y_site = int(design.micronToDBU(max_disp_y_um) / site_height)

# Remove filler cells if they were inserted in a previous run (e.g., from a loaded DEF)
detailed_placer.removeFillers()
# Run detailed placement with specified max displacement
detailed_placer.detailedPlacement(max_disp_x_site, max_disp_y_site, "", False) # "" for design_name, False for verbose_plots
print("Initial detailed placement completed.")

# --- Clock Tree Synthesis (CTS) ---
print("Starting Clock Tree Synthesis (CTS)...")
# Set unit resistance and capacitance for clock and signal wires using Tcl commands
design.evalTclString("set_wire_rc -clock -resistance 0.03574 -capacitance 0.07516")
design.evalTclString("set_wire_rc -signal -resistance 0.03574 -capacitance 0.07516")

# Configure CTS tool
cts = design.getTritonCts()
# Set buffer list, root buffer, and sink buffer to BUF_X2
cts.setBufferList("BUF_X2")
cts.setRootBuffer("BUF_X2")
cts.setSinkBuffer("BUF_X2")
# Run CTS
cts.runTritonCts()
print("CTS completed.")

# Detailed placement after CTS to legalize cells moved/inserted by CTS
print("Starting detailed placement after CTS...")
detailed_placer.detailedPlacement(max_disp_x_site, max_disp_y_site, "", False)
print("Detailed placement after CTS completed.")


# --- Power Delivery Network (PDN) Setup ---
print("Starting PDN setup...")
pdngen = design.getPdnGen()

# Set up global power/ground connections for standard cells
# Find or create VDD and VSS nets in the block
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

# Create VDD/VSS nets if they don't exist and set their signal type and special flag
if VDD_net is None:
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSigType("POWER")
    VDD_net.setSpecial() # Mark as special net
if VSS_net is None:
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSigType("GROUND")
    VSS_net.setSpecial() # Mark as special net

# Connect standard cell power/ground pins to the global VDD/VSS nets
# This uses patterns matching typical power/ground pin names
print("Connecting power and ground pins globally...")
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VDD.*", net=VDD_net, do_connect=True)
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VSS.*", net=VSS_net, do_connect=True)
# Apply the global connections
block.globalConnect()

# Configure the core power domain with VDD and VSS nets
pdngen.setCoreDomain(power=VDD_net, ground=VSS_net, switched_power=None, secondary=list())

# Create a main grid definition for the core domain (standard cells)
domains = [pdngen.findDomain("Core")] # Get the core domain object

# Find required metal layers
m1 = design.getTech().getDB().getTech().findLayer("metal1")
m4 = design.getTech().getDB().getTech().findLayer("metal4")
m5 = design.getTech().getDB().getTech().findLayer("metal5")
m6 = design.getTech().getDB().getTech().findLayer("metal6")
m7 = design.getTech().getDB().getTech().findLayer("metal7")
m8 = design.getTech().getDB().getTech().findLayer("metal8")

if not all([m1, m4, m5, m6, m7, m8]):
    print("Error: One or more required metal layers (metal1, metal4, metal5, metal6, metal7, metal8) not found. Check your LEF.")
    exit()

# Create the core grid object for standard cells
for domain in domains:
    pdngen.makeCoreGrid(domain=domain,
                        name="stdcell_core_grid",
                        starts_with=pdn.GROUND, # Assuming ground pattern starts first, adjust if needed
                        pin_layers=[], # No specific pin layers for core grid boundary
                        generate_obstructions=[],
                        powercell=None, powercontrol=None, powercontrolnetwork="")

# Get the created standard cell core grid object
stdcell_grid = pdngen.findGrid("stdcell_core_grid")[0] # findGrid returns a list

# Add power rings on M7 and M8 around the core area
ring_width_um = 5.0
ring_spacing_um = 5.0
ring_width_dbu = design.micronToDBU(ring_width_um)
ring_spacing_dbu = design.micronToDBU(ring_spacing_um)
ring_offset_dbu = design.micronToDBU(0) # Offset 0 as requested

print("Adding power rings on M7 and M8...")
pdngen.makeRing(grid=stdcell_grid,
                layer0=m7, width0=ring_width_dbu, spacing0=ring_spacing_dbu,
                layer1=m8, width1=ring_width_dbu, spacing1=ring_spacing_dbu,
                starts_with=pdn.GRID, # Start pattern relative to the grid definition
                offset=[ring_offset_dbu]*4, # Offset from the core boundary (left, bottom, right, top)
                pad_offset=[ring_offset_dbu]*4, # No pad offset specified
                extend=False, # Do not extend beyond core boundary
                pad_pin_layers=[], # No connection to pads specified
                nets=[VDD_net, VSS_net]) # Apply rings to VDD and VSS nets

# Add horizontal followpin straps on M1 for standard cell connections
m1_followpin_width_um = 0.07
m1_followpin_width_dbu = design.micronToDBU(m1_followpin_width_um)
print(f"Adding followpin straps on M1 with width {m1_followpin_width_um} um...")
pdngen.makeFollowpin(grid=stdcell_grid,
                     layer=m1,
                     width=m1_followpin_width_dbu,
                     extend=pdn.CORE) # Extend within the core area

# Add vertical strap grid on M4 for standard cells
m4_strap_width_um = 1.2
m4_strap_spacing_um = 1.2
m4_strap_pitch_um = 6.0
m4_strap_width_dbu = design.micronToDBU(m4_strap_width_um)
m4_strap_spacing_dbu = design.micronToDBU(m4_strap_spacing_um)
m4_strap_pitch_dbu = design.micronToDBU(m4_strap_pitch_um)
m4_strap_offset_dbu = design.micronToDBU(0) # Offset 0 as requested

print(f"Adding strap grid on M4 with width {m4_strap_width_um} um, spacing {m4_strap_spacing_um} um, pitch {m4_strap_pitch_um} um...")
pdngen.makeStrap(grid=stdcell_grid,
                 layer=m4,
                 width=m4_strap_width_dbu,
                 spacing=m4_strap_spacing_dbu,
                 pitch=m4_strap_pitch_dbu,
                 offset=m4_strap_offset_dbu,
                 number_of_straps=0, # 0 means calculate number based on pitch/offset within area
                 snap=False, # No snapping specified for M4 straps
                 starts_with=pdn.GRID,
                 extend=pdn.CORE, # Extend within the core area
                 nets=[VDD_net, VSS_net]) # Apply straps to VDD and VSS

# Add strap grid on M7 (already covered by rings, but adding strap def allows for via connections)
# Using specified strap parameters for M7 and M8
m7_m8_strap_width_um = 1.4
m7_m8_strap_spacing_um = 1.4
m7_m8_strap_pitch_um = 10.8
m7_m8_strap_width_dbu = design.micronToDBU(m7_m8_strap_width_um)
m7_m8_strap_spacing_dbu = design.micronToDBU(m7_m8_strap_spacing_um)
m7_m8_strap_pitch_dbu = design.micronToDBU(m7_m8_strap_pitch_um)
m7_m8_strap_offset_dbu = design.micronToDBU(0) # Offset 0 as requested

print(f"Adding strap grid definition on M7/M8 for vias (width {m7_m8_strap_width_um} um, spacing {m7_m8_strap_spacing_um} um, pitch {m7_m8_strap_pitch_um} um)...")
pdngen.makeStrap(grid=stdcell_grid,
                 layer=m7,
                 width=m7_m8_strap_width_dbu,
                 spacing=m7_m8_strap_spacing_dbu,
                 pitch=m7_m8_strap_pitch_dbu,
                 offset=m7_m8_strap_offset_dbu,
                 number_of_straps=0,
                 snap=False,
                 starts_with=pdn.GRID,
                 extend=pdn.CORE, # Extend within the core area
                 nets=[VDD_net, VSS_net]) # Apply straps to VDD and VSS

pdngen.makeStrap(grid=stdcell_grid,
                 layer=m8,
                 width=m7_m8_strap_width_dbu,
                 spacing=m7_m8_strap_spacing_dbu,
                 pitch=m7_m8_strap_pitch_dbu,
                 offset=m7_m8_strap_offset_dbu,
                 number_of_straps=0,
                 snap=False,
                 starts_with=pdn.GRID,
                 extend=pdn.CORE, # Extend within the core area
                 nets=[VDD_net, VSS_net]) # Apply straps to VDD and VSS


# Power Grid for Macros (if macros exist)
if len(macros) > 0:
    print("Setting up PDN for macros...")
    m5_m6_strap_width_um = 1.2
    m5_m6_strap_spacing_um = 1.2
    m5_m6_strap_pitch_um = 6.0
    m5_m6_strap_width_dbu = design.micronToDBU(m5_m6_strap_width_um)
    m5_m6_strap_spacing_dbu = design.micronToDBU(m5_m6_strap_spacing_um)
    m5_m6_strap_pitch_dbu = design.micronToDBU(m5_m6_strap_pitch_um)
    m5_m6_strap_offset_dbu = design.micronToDBU(0) # Offset 0 as requested

    # Iterate through each macro to create its instance grid
    for macro in macros:
        # Create instance grid specific to this macro
        for domain in domains:
            pdngen.makeInstanceGrid(domain=domain,
                                    name=f"macro_grid_{macro.getName()}", # Unique name per macro
                                    starts_with=pdn.GROUND, # Or pdn.POWER
                                    inst=macro,
                                    halo=[design.micronToDBU(0)]*4, # No halo for grid definition itself
                                    pg_pins_to_boundary=True, # Connect macro PG pins to boundary
                                    default_grid=False,
                                    generate_obstructions=[],
                                    is_bump=False)

        # Get the grid object just created for this macro
        macro_instance_grid = pdngen.findGrid(f"macro_grid_{macro.getName()}")[0]

        # Add strap grid on M5 and M6 within the macro boundary
        print(f"Adding strap grid on M5/M6 for macro {macro.getName()} with width {m5_m6_strap_width_um} um, spacing {m5_m6_strap_spacing_um} um, pitch {m5_m6_strap_pitch_um} um...")
        pdngen.makeStrap(grid=macro_instance_grid,
                         layer=m5,
                         width=m5_m6_strap_width_dbu,
                         spacing=m5_m6_strap_spacing_dbu,
                         pitch=m5_m6_strap_pitch_dbu,
                         offset=m5_m6_strap_offset_dbu,
                         number_of_straps=0,
                         snap=True, # Snap to grid for macros as in example
                         starts_with=pdn.GRID,
                         extend=pdn.CORE, # Extend within the macro instance boundary
                         nets=[VDD_net, VSS_net]) # Apply straps to VDD and VSS

        pdngen.makeStrap(grid=macro_instance_grid,
                         layer=m6,
                         width=m5_m6_strap_width_dbu,
                         spacing=m5_m6_strap_spacing_dbu,
                         pitch=m5_m6_strap_pitch_dbu,
                         offset=m5_m6_strap_offset_dbu,
                         number_of_straps=0,
                         snap=True, # Snap to grid for macros as in example
                         starts_with=pdn.GRID,
                         extend=pdn.CORE, # Extend within the macro instance boundary
                         nets=[VDD_net, VSS_net]) # Apply straps to VDD and VSS


# Add via connections between power grid layers
# "pitch of the via between two grids to 0 um" is interpreted as using default via generation rules,
# which the API maps to cut_pitch_x/y = 0 in DBU for automatic rule application.
via_cut_pitch_dbu = [design.micronToDBU(0), design.micronToDBU(0)]

# Connections for Standard Cell Grid: M1-M4, M4-M7, M7-M8
print("Adding via connections for standard cell grid...")
pdngen.makeConnect(grid=stdcell_grid, layer0=m1, layer1=m4, cut_pitch_x=via_cut_pitch_dbu[0], cut_pitch_y=via_cut_pitch_dbu[1],
                   vias=[], techvias=[], max_rows=0, max_columns=0, ongrid=[], split_cuts={}, dont_use_vias="")
pdngen.makeConnect(grid=stdcell_grid, layer0=m4, layer1=m7, cut_pitch_x=via_cut_pitch_dbu[0], cut_pitch_y=via_cut_pitch_dbu[1],
                   vias=[], techvias=[], max_rows=0, max_columns=0, ongrid=[], split_cuts={}, dont_use_vias="")
pdngen.makeConnect(grid=stdcell_grid, layer0=m7, layer1=m8, cut_pitch_x=via_cut_pitch_dbu[0], cut_pitch_y=via_cut_pitch_dbu[1],
                   vias=[], techvias=[], max_rows=0, max_columns=0, ongrid=[], split_cuts={}, dont_use_vias="")

# Connections for Macro Grids (if macros exist)
if len(macros) > 0:
    print("Adding via connections for macro grids...")
    for macro in macros:
        macro_instance_grid = pdngen.findGrid(f"macro_grid_{macro.getName()}")[0]
        # Connections M4-M5, M5-M6, M6-M7 (assuming connection to surrounding stdcell grid layers M4 and M7)
        pdngen.makeConnect(grid=macro_instance_grid, layer0=m4, layer1=m5, cut_pitch_x=via_cut_pitch_dbu[0], cut_pitch_y=via_cut_pitch_dbu[1],
                           vias=[], techvias=[], max_rows=0, max_columns=0, ongrid=[], split_cuts={}, dont_use_vias="")
        pdngen.makeConnect(grid=macro_instance_grid, layer0=m5, layer1=m6, cut_pitch_x=via_cut_pitch_dbu[0], cut_pitch_y=via_cut_pitch_dbu[1],
                           vias=[], techvias=[], max_rows=0, max_columns=0, ongrid=[], split_cuts={}, dont_use_vias="")
        pdngen.makeConnect(grid=macro_instance_grid, layer0=m6, layer1=m7, cut_pitch_x=via_cut_pitch_dbu[0], cut_pitch_y=via_cut_pitch_dbu[1],
                           vias=[], techvias=[], max_rows=0, max_columns=0, ongrid=[], split_cuts={}, dont_use_vias="")

# Verify PDN setup and build the grids (create shapes in the database)
print("Building power grid...")
pdngen.checkSetup()
pdngen.buildGrids(False) # False means do not add shapes to DB yet
pdngen.writeToDb(True) # True means add shapes to DB
pdngen.resetShapes() # Clear internal shapes after writing to DB
print("PDN setup completed.")

# Insert filler cells after PDN and placement
print("Inserting filler cells...")
# Get filler cell masters (assuming naming convention or type "CORE_SPACER")
db = ord.get_db()
filler_masters = list()
# Find filler cells by type (CORE_SPACER is a common type)
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

if len(filler_masters) == 0:
    print("Warning: No CORE_SPACER filler cells found in libraries. Skipping filler insertion.")
else:
    # Perform filler cell placement to fill empty spaces in rows
    # detailed_placer object was already obtained earlier
    detailed_placer.fillerPlacement(filler_masters=filler_masters,
                                    prefix="FILLCELL_", # Prefix for created filler instances
                                    verbose=False)
    print("Filler cell insertion completed.")

# --- Routing ---
print("Starting routing...")
global_router = design.getGlobalRouter()

# Find routing layers M1 and M7
m1_layer = design.getTech().getDB().getTech().findLayer("metal1")
m7_layer = design.getTech().getDB().getTech().findLayer("metal7")

if not m1_layer or not m7_layer:
     print("Error: Metal layers metal1 or metal7 not found for routing. Please check your LEF.")
     exit()

# Set routing layer range for global routing from M1 to M7
signal_low_layer = m1_layer.getRoutingLevel()
signal_high_layer = m7_layer.getRoutingLevel()
clk_low_layer = m1_layer.getRoutingLevel() # Clock routing uses the same layers as signal
clk_high_layer = m7_layer.getRoutingLevel()

global_router.setMinRoutingLayer(signal_low_layer)
global_router.setMaxRoutingLayer(signal_high_layer)
global_router.setMinLayerForClock(clk_low_layer)
global_router.setMaxLayerForClock(clk_high_layer)
global_router.setAdjustment(0.5) # Default adjustment value for congestion
global_router.setVerbose(True)
# Run global routing
print("Running global routing...")
global_router.globalRoute(True) # True means adjust routability based on congestion

# Detailed Routing
print("Starting detailed routing...")
detailed_router = design.getTritonRoute()
dr_params = drt.ParamStruct()

# Set detailed routing parameters
dr_params.outputMazeFile = "" # No maze file output
dr_params.outputDrcFile = "droute.drc" # Output DRC violations file
dr_params.outputCmapFile = "" # No cmap file output
dr_params.outputGuideCoverageFile = "" # No guide coverage file output
dr_params.dbProcessNode = "" # Leave empty unless specified by technology
dr_params.enableViaGen = True # Enable via generation
dr_params.drouteEndIter = 1 # Number of detailed routing iterations
dr_params.viaInPinBottomLayer = "" # No specific layers for via-in-pin specified
dr_params.viaInPinTopLayer = ""
dr_params.orSeed = -1 # Default seed
dr_params.orK = 0 # Default K value
dr_params.bottomRoutingLayer = "metal1" # Set bottom routing layer name
dr_params.topRoutingLayer = "metal7" # Set top routing layer name
dr_params.verbose = 1 # Verbose output level
dr_params.cleanPatches = True # Clean routing patches
dr_params.doPa = True # Perform post-routing access analysis
dr_params.singleStepDR = False # Do not run in single-step mode
dr_params.minAccessPoints = 1 # Default minimum access points

detailed_router.setParams(dr_params)
# Run detailed routing
detailed_router.main()
print("Routing completed.")

# --- Power Analysis ---
print("Starting static IR drop analysis...")
psm_obj = design.getPDNSim()
timing = Timing(design) # Need timing object for corner definition

# Get the VDD net for IR drop analysis
VDD_net_for_ir = block.findNet("VDD")
if not VDD_net_for_ir:
     print("Error: VDD net not found for IR drop analysis. Cannot perform IR drop analysis.")
     # Skip analysis if VDD net is not found
else:
    # Define source types for analysis (standard cells, straps, bumps)
    source_types = [psm.GeneratedSourceType_FULL,
                    psm.GeneratedSourceType_STRAPS,
                    psm.GeneratedSourceType_BUMPS]

    # IR drop analysis requires activity (timing corners). Check if corners exist.
    corners = timing.getCorners()
    if not corners:
        print("Warning: No timing corners found. Static IR drop analysis may not be accurate without activity. Using default settings.")
        # Perform analysis without a specified corner if none exist
        # analyzePowerGrid usually expects a corner object. Let's check if it can run without one.
        # Based on example, a corner is required. If no corner, we must skip or add a dummy.
        # For this script, if no corners are loaded, we skip IR drop analysis.
        print("Skipping static IR drop analysis due to missing timing corners.")
    else:
        # Perform static IR drop analysis on the VDD net using the first available timing corner
        # The analysis is performed on the net, covering all layers it uses (M1, M4, M7, M8 etc for VDD)
        print(f"Analyzing IR drop on net {VDD_net_for_ir.getName()} for corner {corners[0].getName()}...")
        psm_obj.analyzePowerGrid(net = VDD_net_for_ir,
                                 enable_em = False, # EM analysis disabled as not requested
                                 corner = corners[0], # Use the first timing corner
                                 use_prev_solution = False, # Do not use previous solution
                                 em_file = "", # No EM file output
                                 error_file = "irdrop.error", # Output error file name
                                 voltage_source_file = "", # No specific voltage source file
                                 voltage_file = "irdrop.voltage", # Output voltage file name
                                 source_type = source_types[0]) # Using FULL source type (includes standard cells, macros, rings, straps)
        print("Static IR drop analysis completed. Results in irdrop.voltage and irdrop.error.")


# Report power (switching, internal, leakage) - typically done after timing analysis with activity
# This Tcl command requires power data to be available (e.g., from a prior timing analysis run with activity)
print("Reporting power (requires prior timing analysis with activity)...")
design.evalTclString("report_power")

# --- Finalize ---
# Dump the final DEF file
output_def_file = "final.def"
print(f"Writing final DEF file: {output_def_file}...")
design.writeDef(output_def_file)

print("OpenROAD flow script finished.")