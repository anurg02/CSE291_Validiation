from openroad import Tech, Design, Timing
from pathlib import Path
import pdn, odb, drt, psm
import openroad as ord # Using ord for getting db

# --- 1. Load Technology and Design ---

# Initialize OpenROAD objects
tech = Tech()

# Set paths to library and design files (example paths)
libDir = Path("../Design/nangate45/lib")
lefDir = Path("../Design/nangate45/lef")
designDir = Path("../Design/")

# Specify design details
design_name = "1_synth" # Assuming verilog file is 1_synth.v
design_top_module_name = "gcd" # Assuming top module name is gcd

# Read all liberty (.lib) and LEF files from the library directories
libFiles = libDir.glob("*.lib")
techLefFiles = lefDir.glob("*.tech.lef")
lefFiles = lefDir.glob('*.lef')

# Load liberty timing libraries
for libFile in libFiles:
    tech.readLiberty(libFile.as_posix())
# Load technology and cell LEF files
for techLefFile in techLefFiles:
    tech.readLef(techLefFile.as_posix())
for lefFile in lefFiles:
    tech.readLef(lefFile.as_posix())

# Create design and read Verilog netlist
design = Design(tech)
verilogFile = designDir/str(design_name + ".v")
design.readVerilog(verilogFile.as_posix())
# Link the design to resolve instances and connections based on LEF/Liberty
design.link(design_top_module_name)

# --- 2. Clock Setup ---

clock_period_ns = 40
clock_port_name = "clk"
clock_name = "core_clock"

# Create clock signal on the specified port
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
# Propagate the clock signal
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# --- 3. Floorplanning ---

# Initialize floorplan
floorplan = design.getFloorplan()

# Get site for floorplan initialization (assuming a site exists)
site = None
for s in design.getTech().getDB().getTech().getSites():
    site = s
    break
if not site:
    print("ERROR: No site found in technology LEF.")
    exit()

target_utilization = 0.50
aspect_ratio = 1.0 # Default aspect ratio
core_margin_micron = 5.0
core_margin_dbu = design.micronToDBU(core_margin_micron)

# Initialize floorplan with core and die area based on utilization and margin
floorplan.initFloorplan(target_utilization, aspect_ratio, core_margin_dbu, core_margin_dbu, core_margin_dbu, core_margin_dbu, site)
# Make tracks based on the floorplan
floorplan.makeTracks()

# --- 4. IO Placement ---

# Configure and run I/O pin placement
io_placer = design.getIOPlacer()
params = io_placer.getParameters()
params.setRandSeed(42) # Set random seed for reproducibility
params.setMinDistanceInTracks(False) # Specify distance in DBU, not tracks
params.setMinDistance(design.micronToDBU(0)) # Minimum distance between pins
params.setCornerAvoidance(design.micronToDBU(0)) # Avoid corners by this margin

# Find routing layers for IO placement
m8_layer = design.getTech().getDB().getTech().findLayer("metal8")
m9_layer = design.getTech().getDB().getTech().findLayer("metal9")

if m8_layer and m9_layer:
    # Place I/O pins on metal8 (horizontal preference) and metal9 (vertical preference) layers
    io_placer.addHorLayer(m8_layer)
    io_placer.addVerLayer(m9_layer)
    # Run IO placement using annealing
    IOPlacer_random_mode = True # Set to True for random initialization
    io_placer.runAnnealing(IOPlacer_random_mode)
else:
    print("WARNING: metal8 or metal9 not found. Skipping IO placement.")


# --- 5. Macro Placement ---

# Check if there are any macros in the design
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    print(f"INFO: Found {len(macros)} macros. Running macro placement.")
    mpl = design.getMacroPlacer()
    block = design.getBlock()
    core = block.getCoreArea()

    # Macro halo and fence parameters
    macro_halo_micron = 5.0
    macro_halo_dbu = design.micronToDBU(macro_halo_micron)

    # Note: The API doesn't directly support "minimum distance between macros"
    # but halo helps keep std cells away.
    # Fence region is set to the core area to keep macros inside the core boundary.
    mpl.place(
        # General parameters (can be adjusted based on design scale and requirements)
        num_threads = 64,
        max_num_macro = len(macros), # Allow placing all macros
        min_num_macro = 0,
        max_num_inst = 0, # Do not place standard cells with macros
        min_num_inst = 0,
        tolerance = 0.1,
        max_num_level = 2,
        coarsening_ratio = 10.0,
        large_net_threshold = 50,
        signature_net_threshold = 50,
        # Macro-specific parameters
        halo_width = macro_halo_micron,
        halo_height = macro_halo_micron,
        fence_lx = block.dbuToMicrons(core.xMin()),
        fence_ly = block.dbuToMicrons(core.yMin()),
        fence_ux = block.dbuToMicrons(core.xMax()),
        fence_uy = block.dbuToMicrons(core.yMax()),
        # Weight parameters (adjust based on desired optimization goals)
        area_weight = 0.1,
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        pin_access_th = 0.0,
        target_util = 0.25, # Target utilization during macro placement (internal heuristic)
        target_dead_space = 0.05,
        min_ar = 0.33,
        snap_layer = 4, # Example snap layer index
        bus_planning_flag = False,
        report_directory = ""
    )
else:
    print("INFO: No macros found in the design. Skipping macro placement.")


# --- 6. Global Placement ---

gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Can be set to True for timing optimization
gpl.setRoutabilityDrivenMode(True) # Enable routability optimization
gpl.setUniformTargetDensityMode(True) # Use uniform target density
# Set the number of initial placement iterations as requested
gpl.setInitialPlaceMaxIter(30)
gpl.setInitDensityPenalityFactor(0.05)

# Run initial placement steps
gpl.doInitialPlace(threads = 4)
gpl.doNesterovPlace(threads = 4) # Nesterov-based optimization
gpl.reset() # Reset placer state

# --- 7. Detailed Placement ---

# Remove filler cells that might have been inserted earlier (though none were yet)
# This is necessary before detailed placement can move cells.
design.getOpendp().removeFillers()

# Set maximum displacement for detailed placement
max_disp_x_micron = 1.0
max_disp_y_micron = 3.0

# Get site dimensions to convert micron displacement to site units (OpenDP works in site units)
site = design.getBlock().getRows()[0].getSite()
max_disp_x_site = int(design.micronToDBU(max_disp_x_micron) / site.getWidth())
max_disp_y_site = int(design.micronToDBU(max_disp_y_micron) / site.getHeight())

# Run detailed placement
design.getOpendp().detailedPlacement(max_disp_x_site, max_disp_y_site, "", False)


# --- 8. Clock Tree Synthesis (CTS) ---

# Get the CTS tool object
cts = design.getTritonCts()

# Set RC values for clock and signal nets (using evalTclString as shown in examples)
design.evalTclString(f"set_wire_rc -clock -resistance {0.03574} -capacitance {0.07516}")
design.evalTclString(f"set_wire_rc -signal -resistance {0.03574} -capacitance {0.07516}")

# Configure clock buffers (using BUF_X2)
buffer_cell_name = "BUF_X2"
cts.setBufferList(buffer_cell_name)
cts.setRootBuffer(buffer_cell_name) # Set buffer for clock root
cts.setSinkBuffer(buffer_cell_name) # Set buffer for clock sinks

# Run CTS
cts.runTritonCts()

# Run detailed placement again after CTS to fix cell locations
# Convert max displacement to site units based on the site dimensions
design.getOpendp().detailedPlacement(max_disp_x_site, max_disp_y_site, "", False)


# --- 9. Power Delivery Network (PDN) Setup ---

pdngen = design.getPdnGen()

# Set up global power/ground connections
# Find VDD/VSS nets or create them if they don't exist
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")

if VDD_net is None:
    VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
    VDD_net.setSigType("POWER")
    VDD_net.setSpecial() # Mark as special net
if VSS_net is None:
    VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
    VSS_net.setSigType("GROUND")
    VSS_net.setSpecial() # Mark as special net

# Connect standard cell power pins to global nets
# Uses patterns to match instance names and pin names
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
# Execute global connection
design.getBlock().globalConnect()

# Configure core voltage domain
# Assume a single core domain covering the whole design
pdngen.setCoreDomain(power = VDD_net, switched_power = None, ground = VSS_net, secondary = list())

# Create power grid for standard cells (Core Grid)
# This creates the base grid structure within the core domain
domains = [pdngen.findDomain("Core")] # Get the core domain object
for domain in domains:
    pdngen.makeCoreGrid(domain = domain,
    name = "core_stdcell_grid", # Name for the core grid
    starts_with = pdn.GROUND, # Can start with POWER or GROUND
    pin_layers = [], # Layers to connect pins to (usually followpin takes care of this)
    generate_obstructions = [], # Layers to generate obstructions on
    powercell = None, # Power cell master for followpin (optional)
    powercontrol = None, # Power control net (optional)
    powercontrolnetwork = "STAR") # Power control network type (optional)

# Get the created core grid
core_grid = pdngen.findGrid("core_stdcell_grid")[0] # Assuming only one core grid

# Get routing layers for PDN construction
m1 = design.getTech().getDB().getTech().findLayer("metal1")
m4 = design.getTech().getDB().getTech().findLayer("metal4")
m5 = design.getTech().getDB().getTech().findLayer("metal5")
m6 = design.getTech().getDB().getTech().findLayer("metal6")
m7 = design.getTech().getDB().getTech().findLayer("metal7")
m8 = design.getTech().getDB().getTech().findLayer("metal8")

# Ensure layers exist
if not all([m1, m4, m5, m6, m7, m8]):
    print("ERROR: Required metal layers for PDN not found in technology.")
    exit()

# Add Rings for Standard Cells (on M7 and M8)
ring_width_micron = 5.0
ring_spacing_micron = 5.0
ring_width_dbu = design.micronToDBU(ring_width_micron)
ring_spacing_dbu = design.micronToDBU(ring_spacing_micron)
offset_dbu = design.micronToDBU(0) # Offset is 0 as requested
offsets_dbu = [offset_dbu, offset_dbu, offset_dbu, offset_dbu]

pdngen.makeRing(grid = core_grid,
    layer0 = m7, width0 = ring_width_dbu, spacing0 = ring_spacing_dbu,
    layer1 = m8, width1 = ring_width_dbu, spacing1 = ring_spacing_dbu,
    starts_with = pdn.GRID, # Determines starting layer for stripes
    offset = offsets_dbu, # Offset from boundary (bottom, top, left, right)
    pad_offset = offsets_dbu, # Offset for pads (not used here)
    extend = False, # Do not extend beyond ring definition
    pad_pin_layers = list(), # Layers to connect pads to
    nets = list()) # Apply to all nets in domain (VDD/VSS)

# Add Followpin Straps for Standard Cells (on M1)
m1_followpin_width_micron = 0.07
m1_followpin_width_dbu = design.micronToDBU(m1_followpin_width_micron)
pdngen.makeFollowpin(grid = core_grid,
    layer = m1,
    width = m1_followpin_width_dbu,
    extend = pdn.CORE) # Extend within the core area

# Add Strap Straps for Standard Cells (on M4, M7, M8)
m4_strap_width_micron = 1.2
m4_strap_spacing_micron = 1.2
m4_strap_pitch_micron = 6.0
m4_strap_width_dbu = design.micronToDBU(m4_strap_width_micron)
m4_strap_spacing_dbu = design.micronToDBU(m4_strap_spacing_micron)
m4_strap_pitch_dbu = design.micronToDBU(m4_strap_pitch_micron)

m7_strap_width_micron = 1.4
m7_strap_spacing_micron = 1.4
m7_strap_pitch_micron = 10.8
m7_strap_width_dbu = design.micronToDBU(m7_strap_width_micron)
m7_strap_spacing_dbu = design.micronToDBU(m7_strap_spacing_micron)
m7_strap_pitch_dbu = design.micronToDBU(m7_strap_pitch_micron)

m8_strap_width_micron = 1.4 # Re-using M7 values as requested for M8 straps
m8_strap_spacing_micron = 1.4
m8_strap_pitch_micron = 10.8
m8_strap_width_dbu = design.micronToDBU(m8_strap_width_micron)
m8_strap_spacing_dbu = design.micronToDBU(m8_strap_spacing_micron)
m8_strap_pitch_dbu = design.micronToDBU(m8_strap_pitch_micron)


# M4 vertical straps
pdngen.makeStrap(grid = core_grid,
    layer = m4,
    width = m4_strap_width_dbu,
    spacing = m4_strap_spacing_dbu,
    pitch = m4_strap_pitch_dbu,
    offset = offset_dbu,
    number_of_straps = 0, # Generate based on pitch
    snap = False, # Do not snap to track grid
    starts_with = pdn.GRID,
    extend = pdn.CORE,
    nets = list())

# M7 vertical straps
pdngen.makeStrap(grid = core_grid,
    layer = m7,
    width = m7_strap_width_dbu,
    spacing = m7_strap_spacing_dbu,
    pitch = m7_strap_pitch_dbu,
    offset = offset_dbu,
    number_of_straps = 0,
    snap = False,
    starts_with = pdn.GRID,
    extend = pdn.RINGS, # Extend up to the rings
    nets = list())

# M8 horizontal straps
pdngen.makeStrap(grid = core_grid,
    layer = m8,
    width = m8_strap_width_dbu,
    spacing = m8_strap_spacing_dbu,
    pitch = m8_strap_pitch_dbu,
    offset = offset_dbu,
    number_of_straps = 0,
    snap = False,
    starts_with = pdn.GRID,
    extend = pdn.BOUNDARY, # Extend to the boundary
    nets = list())

# Create Power Grids for Macros (if any)
if len(macros) > 0:
    m5_macro_width_micron = 1.2
    m5_macro_spacing_micron = 1.2
    m5_macro_pitch_micron = 6.0
    m5_macro_width_dbu = design.micronToDBU(m5_macro_width_micron)
    m5_macro_spacing_dbu = design.micronToDBU(m5_macro_spacing_micron)
    m5_macro_pitch_dbu = design.micronToDBU(m5_macro_pitch_micron)

    m6_macro_width_micron = 1.2 # Re-using M5 values as requested for M6
    m6_macro_spacing_micron = 1.2
    m6_macro_pitch_micron = 6.0
    m6_macro_width_dbu = design.micronToDBU(m6_macro_width_micron)
    m6_macro_spacing_dbu = design.micronToDBU(m6_macro_spacing_micron)
    m6_macro_pitch_dbu = design.micronToDBU(m6_macro_pitch_micron)

    # Macro halo (same as placement halo for consistency)
    macro_pdn_halo_dbu = [macro_halo_dbu, macro_halo_dbu, macro_halo_dbu, macro_halo_dbu] # bottom, top, left, right

    for i, macro_inst in enumerate(macros):
        # Create instance grid for each macro
        # pg_pins_to_boundary=True means macro power pins are assumed to be on the boundary
        pdngen.makeInstanceGrid(domain = domains[0], # Use the core domain
            name = f"macro_grid_{i}",
            starts_with = pdn.GROUND,
            inst = macro_inst,
            halo = macro_pdn_halo_dbu,
            pg_pins_to_boundary = True, # Set based on macro LEF definition
            default_grid = False,
            generate_obstructions = [],
            is_bump = False)

        # Get the created macro grid
        macro_grid = pdngen.findGrid(f"macro_grid_{i}")[0]

        # Add M5 straps for macro PDN (e.g., horizontal)
        pdngen.makeStrap(grid = macro_grid,
            layer = m5,
            width = m5_macro_width_dbu,
            spacing = m5_macro_spacing_dbu,
            pitch = m5_macro_pitch_dbu,
            offset = offset_dbu,
            number_of_straps = 0,
            snap = True, # Snap to track grid if applicable
            starts_with = pdn.GRID,
            extend = pdn.CORE, # Extend within the macro instance boundary
            nets = list())

        # Add M6 straps for macro PDN (e.g., vertical)
        pdngen.makeStrap(grid = macro_grid,
            layer = m6,
            width = m6_macro_width_dbu,
            spacing = m6_macro_spacing_dbu,
            pitch = m6_macro_pitch_dbu,
            offset = offset_dbu,
            number_of_straps = 0,
            snap = True,
            starts_with = pdn.GRID,
            extend = pdn.CORE,
            nets = list())


# Add Connections (Vias) between layers
# cut_pitch = 0 uses the default technology via generation rules
cut_pitch_dbu_x = design.micronToDBU(0)
cut_pitch_dbu_y = design.micronToDBU(0)

# Standard cell grid connections
pdngen.makeConnect(grid = core_grid, layer0 = m1, layer1 = m4, cut_pitch_x = cut_pitch_dbu_x, cut_pitch_y = cut_pitch_dbu_y)
pdngen.makeConnect(grid = core_grid, layer0 = m4, layer1 = m7, cut_pitch_x = cut_pitch_dbu_x, cut_pitch_y = cut_pitch_dbu_y)
pdngen.makeConnect(grid = core_grid, layer0 = m7, layer1 = m8, cut_pitch_x = cut_pitch_dbu_x, cut_pitch_y = cut_pitch_dbu_y)

# Macro grid connections (if macros exist)
if len(macros) > 0:
     for i, macro_inst in enumerate(macros):
        macro_grid = pdngen.findGrid(f"macro_grid_{i}")[0]
        # Assuming M4-M5, M5-M6, M6-M7 connections for macro grids
        pdngen.makeConnect(grid = macro_grid, layer0 = m4, layer1 = m5, cut_pitch_x = cut_pitch_dbu_x, cut_pitch_y = cut_pitch_dbu_y)
        pdngen.makeConnect(grid = macro_grid, layer0 = m5, layer1 = m6, cut_pitch_x = cut_pitch_dbu_x, cut_pitch_y = cut_pitch_dbu_y)
        pdngen.makeConnect(grid = macro_grid, layer0 = m6, layer1 = m7, cut_pitch_x = cut_pitch_dbu_x, cut_pitch_y = cut_pitch_dbu_y)


# Verify PDN setup and build the grids (generates shapes)
pdngen.checkSetup()
pdngen.buildGrids(False) # False means build for all voltage domains
pdngen.writeToDb(True, ) # Write generated PDN shapes to the database
pdngen.resetShapes() # Reset shapes in the PDN generator memory after writing


# --- Final Detailed Placement (after PDN if needed, though typically done after CTS) ---
# Re-running detailed placement after PDN creation is sometimes done to fix any issues,
# but often placement after CTS is sufficient before routing. Sticking to the CTS-then-DP flow.


# --- Insert Filler Cells ---
db = ord.get_db()
filler_masters = list()
# Search for filler cells in the library (assuming common naming convention)
filler_cells_prefix = "FILLCELL_" # Adjust prefix if needed
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER" or master.getType() == "SPACER":
            filler_masters.append(master)

if len(filler_masters) == 0:
    print("WARNING: No filler cells found in library. Skipping filler placement.")
else:
    print(f"INFO: Found {len(filler_masters)} filler cell masters. Inserting fillers.")
    # Insert filler cells into empty spaces in the core area
    design.getOpendp().fillerPlacement(filler_masters = filler_masters,
                                     prefix = filler_cells_prefix,
                                     verbose = False)


# --- 10. Routing ---

# Configure Global Router
grt = design.getGlobalRouter()

# Set routing layer range (M1 to M7)
m1_level = design.getTech().getDB().getTech().findLayer("metal1").getRoutingLevel()
m7_level = design.getTech().getDB().getTech().findLayer("metal7").getRoutingLevel()

grt.setMinRoutingLayer(m1_level)
grt.setMaxRoutingLayer(m7_level)
grt.setMinLayerForClock(m1_level) # Clock nets can also use this range
grt.setMaxLayerForClock(m7_level)
grt.setAdjustment(0.5) # Congestion adjustment factor
grt.setVerbose(True)

# Run Global Routing
grt.globalRoute(True) # True to enable timing-driven global routing

# Configure Detailed Router
drter = design.getTritonRoute()
params = drt.ParamStruct()

# Set detailed routing parameters (adjust as needed)
params.outputMazeFile = ""
params.outputDrcFile = "" # Specify a file name to output DRC violations
params.outputCmapFile = ""
params.outputGuideCoverageFile = ""
params.dbProcessNode = "" # Specific process node if required
params.enableViaGen = True # Enable via generation
params.drouteEndIter = 1 # Number of detailed routing iterations
params.viaInPinBottomLayer = "" # Constraint for via-in-pin on bottom layer
params.viaInPinTopLayer = "" # Constraint for via-in-pin on top layer
params.orSeed = -1 # Random seed for detailed router
params.orK = 0
params.bottomRoutingLayer = "metal1" # Bottom layer name
params.topRoutingLayer = "metal7" # Top layer name
params.verbose = 1 # Verbosity level
params.cleanPatches = True # Clean routing patches
params.doPa = True # Perform post-route antenna fixing
params.singleStepDR = False
params.minAccessPoints = 1 # Minimum access points for pins
params.saveGuideUpdates = False

drter.setParams(params)

# Run Detailed Routing
drter.main()


# --- Finalize ---

# Example: Save the final database state
final_odb_file = "final.odb"
design.writeDb(final_odb_file)
print(f"INFO: Final design saved to {final_odb_file}")

# Optional: Run static IR drop analysis (example based on previous script)
# psm_obj = design.getPDNSim()
# timing = Timing(design) # Need a timing object for corners
# source_types = [psm.GeneratedSourceType_FULL] # Specify source types
# if VDD_net:
#     print("INFO: Running static IR drop analysis on VDD.")
#     psm_obj.analyzePowerGrid(net = VDD_net,
#         enable_em = False,
#         corner = timing.getCorners()[0] if timing.getCorners() else None, # Use first timing corner
#         use_prev_solution = False,
#         em_file = "", error_file = "", voltage_source_file = "", voltage_file = "",
#         source_type = source_types[0])
# else:
#     print("WARNING: VDD net not found for IR drop analysis.")

# Optional: Report power (example based on previous script)
# print("INFO: Reporting power...")
# design.evalTclString("report_power")