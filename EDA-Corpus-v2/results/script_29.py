from openroad import Tech, Design, Timing
from pathlib import Path
import odb
import pdn
import drt
import openroad as ord

# Initialize OpenROAD objects and read technology files
tech = Tech()

# Set paths to library and design files (assuming standard structure)
# Modify these paths based on your actual directory structure
libDir = Path("./lib")
lefDir = Path("./lef")
designDir = Path("./")

# Design details
design_name = "your_design_name" # Replace with your actual design name
design_top_module_name = "your_top_module_name" # Replace with your actual top module name
verilog_file = designDir / f"{design_name}.v"

# Read all liberty (.lib) and LEF files from the library directories
libFiles = libDir.glob("*.lib")
techLefFiles = lefDir.glob("*.tech.lef")
lefFiles = lefDir.glob('*.lef')

# Load liberty timing libraries
print("Loading liberty files...")
for libFile in libFiles:
    tech.readLiberty(libFile.as_posix())

# Load technology and cell LEF files
print("Loading LEF files...")
for techLefFile in techLefFiles:
    tech.readLef(techLefFile.as_posix())
for lefFile in lefFiles:
    tech.readLef(lefFile.as_posix())

# Create design and read Verilog netlist
print(f"Reading Verilog netlist: {verilog_file}")
design = Design(tech)
design.readVerilog(verilog_file.as_posix())

# Link the top module
print(f"Linking design top module: {design_top_module_name}")
design.link(design_top_module_name)

# Write initial DEF
print("Writing initial DEF...")
design.writeDef("initial.def")

# Configure and create clock
clock_period_ns = 40
clock_port_name = "clk" # Replace with your actual clock port name
clock_name = "core_clock"
print(f"Creating clock '{clock_name}' on port '{clock_port_name}' with period {clock_period_ns} ns")
# Create clock signal using Tcl command
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
# Propagate the clock signal
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Initialize floorplan with die and core area
print("Initializing floorplan...")
floorplan = design.getFloorplan()
# Define die area (0,0) to (45,45) um
die_lx, die_ly, die_ux, die_uy = 0, 0, 45, 45
die_area = odb.Rect(design.micronToDBU(die_lx), design.micronToDBU(die_ly),
                    design.micronToDBU(die_ux), design.micronToDBU(die_uy))
# Define core area (5,5) to (40,40) um
core_lx, core_ly, core_ux, core_uy = 5, 5, 40, 40
core_area = odb.Rect(design.micronToDBU(core_lx), design.micronToDBU(core_ly),
                     design.micronToDBU(core_ux), design.micronToDBU(core_uy))

# Find a suitable site from the technology library
# Assumes a site named "FreePDK45_38x28_10R_NP_162NW_34O" exists, replace if needed
site_name = "FreePDK45_38x28_10R_NP_162NW_34O"
site = floorplan.findSite(site_name)
if not site:
    # Fallback: try to find any core site
    for s in design.getTech().getDB().getTech().getSites():
        if s.getClass() == "CORE":
            site = s
            print(f"Warning: Specific site '{site_name}' not found. Using site '{site.getName()}' instead.")
            break
    if not site:
        raise ValueError("No CORE site found in the technology library.")


# Initialize the floorplan using the defined areas and site
floorplan.initFloorplan(die_area, core_area, site)
# Create routing tracks based on the site definition
floorplan.makeTracks()

# Write floorplanned DEF
print("Writing floorplanned DEF...")
design.writeDef("floorplan.def")

# Place macro blocks if present
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
if len(macros) > 0:
    print(f"Found {len(macros)} macros. Running macro placement...")
    mpl = design.getMacroPlacer()
    block = design.getBlock()
    
    # Define fence region for macros (5,5) to (20,25) um
    fence_lx, fence_ly, fence_ux, fence_uy = 5, 5, 20, 25

    # Configure macro placement parameters
    # Halo around macros (5 um)
    halo_width = 5.0
    halo_height = 5.0
    # Minimum distance between macros (5 um)
    min_macro_dist = 5.0 # Not directly supported in `place` API, typically handled by density/congestion settings or separate flow

    mpl.place(
        num_threads = 64,
        # The following parameters may need tuning based on design complexity
        max_num_macro = len(macros), # Place all macros
        min_num_macro = 0,
        max_num_inst = 0, # Don't consider standard cells
        min_num_inst = 0,
        tolerance = 0.1,
        max_num_level = 2,
        coarsening_ratio = 10.0,
        large_net_threshold = 50,
        signature_net_threshold = 50,
        halo_width = halo_width,
        halo_height = halo_height,
        # Set fence region
        fence_lx = fence_lx,
        fence_ly = fence_ly,
        fence_ux = fence_ux,
        fence_uy = fence_uy,
        area_weight = 0.1,
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        pin_access_th = 0.0,
        target_util = 0.25, # Target utilization, may need tuning
        target_dead_space = 0.05,
        min_ar = 0.33,
        #snap_layer = 4, # Not explicitly requested, remove or set based on tech
        bus_planning_flag = False,
        report_directory = "" # Disable report directory creation
    )

    # Write macro placed DEF
    print("Writing macro placed DEF...")
    design.writeDef("macro_placed.def")
else:
    print("No macros found. Skipping macro placement.")


# Configure and run global placement
print("Running global placement...")
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Set to True for timing driven placement
gpl.setRoutabilityDrivenMode(True)
gpl.setUniformTargetDensityMode(True)
# Use default initial and Nesterov placement iterations
gpl.doInitialPlace(threads = 4)
gpl.doNesterovPlace(threads = 4)
gpl.reset() # Reset placement engines for subsequent steps

# Write global placed DEF
print("Writing global placed DEF...")
design.writeDef("global_placed.def")

# Run initial detailed placement
print("Running detailed placement...")
# Allow 1um x-displacement and 3um y-displacement
max_disp_x_um = 1.0
max_disp_y_um = 3.0
max_disp_x = int(design.micronToDBU(max_disp_x_um))
max_disp_y = int(design.micronToDBU(max_disp_y_um))

# Remove filler cells if they were inserted earlier (unlikely at this stage, but good practice)
design.getOpendp().removeFillers()
# Perform detailed placement
design.getOpendp().detailedPlacement(max_disp_x, max_disp_y, "", False)

# Write detailed placed DEF
print("Writing detailed placed DEF...")
design.writeDef("detailed_placed.def")


# Configure and run clock tree synthesis
print("Running Clock Tree Synthesis (CTS)...")
# Ensure clock propagation is set
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")
# Set RC values for clock and signal nets
rc_resistance = 0.03574
rc_capacitance = 0.07516
print(f"Setting wire RC values: Resistance={rc_resistance}, Capacitance={rc_capacitance}")
design.evalTclString(f"set_wire_rc -clock -resistance {rc_resistance} -capacitance {rc_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {rc_resistance} -capacitance {rc_capacitance}")

cts = design.getTritonCts()
parms = cts.getParms()
parms.setWireSegmentUnit(20) # Example parameter, may need tuning
# Configure clock buffers
buffer_cell_name = "BUF_X2" # Replace with actual buffer cell name from your library
print(f"Setting CTS buffer cells to '{buffer_cell_name}'")
cts.setBufferList(buffer_cell_name)
cts.setRootBuffer(buffer_cell_name)
cts.setSinkBuffer(buffer_cell_name)
# Run CTS
cts.runTritonCts()

# Write CTS DEF
print("Writing CTS DEF...")
design.writeDef("cts.def")

# Insert filler cells
print("Inserting filler cells...")
db = ord.get_db()
filler_masters = list()
# Example filler cell naming convention
filler_cells_prefix = "FILLCELL_" # Adjust if your library uses a different prefix
# Find filler masters in the library (assuming CORE_SPACER type)
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

if len(filler_masters) == 0:
    print("Warning: No filler cells found in library!")
else:
    print(f"Found {len(filler_masters)} filler cell masters. Performing filler placement...")
    # Perform filler placement
    design.getOpendp().fillerPlacement(filler_masters = filler_masters,
                                     prefix = filler_cells_prefix,
                                     verbose = False)

# Write DEF with fillers
print("Writing DEF after filler insertion...")
design.writeDef("fillers.def")

# Configure and build power delivery network (PDN)
print("Constructing Power Delivery Network (PDN)...")
pdngen = design.getPdnGen()

# Set up global power/ground connections
# Mark power/ground nets as special nets
for net in design.getBlock().getNets():
    if net.getSigType() == "POWER" or net.getSigType() == "GROUND":
        net.setSpecial()

# Find existing power and ground nets or create if needed
VDD_net_name = "VDD" # Replace if your power net has a different name
VSS_net_name = "VSS" # Replace if your ground net has a different name
VDD_net = design.getBlock().findNet(VDD_net_name)
VSS_net = design.getBlock().findNet(VSS_net_name)

# Create VDD/VSS nets if they don't exist (should ideally exist from Verilog/LEF)
if VDD_net is None:
    print(f"Creating VDD net '{VDD_net_name}'")
    VDD_net = odb.dbNet_create(design.getBlock(), VDD_net_name)
    VDD_net.setSpecial()
    VDD_net.setSigType("POWER")
if VSS_net is None:
    print(f"Creating VSS net '{VSS_net_name}'")
    VSS_net = odb.dbNet_create(design.getBlock(), VSS_net_name)
    VSS_net.setSpecial()
    VSS_net.setSigType("GROUND")

# Connect power pins to global nets (adjust pin patterns as needed)
print("Connecting PG pins to global nets...")
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD.*", net = VDD_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS.*", net = VSS_net, do_connect = True)
design.getBlock().globalConnect() # Apply the global connections

# Configure core power domain
pdngen.setCoreDomain(power = VDD_net, ground = VSS_net, switched_power = None, secondary = list())
domains = [pdngen.findDomain("Core")]

# Get metal layers by name
m1 = design.getTech().getDB().getTech().findLayer("metal1")
m4 = design.getTech().getDB().getTech().findLayer("metal4")
m5 = design.getTech().getDB().getTech().findLayer("metal5")
m6 = design.getTech().getDB().getTech().findLayer("metal6")
m7 = design.getTech().getDB().getTech().findLayer("metal7")
m8 = design.getTech().getDB().getTech().findLayer("metal8")

# Check if required layers exist
if not all([m1, m4, m5, m6, m7, m8]):
     print("Error: Required metal layers (metal1, metal4, metal5, metal6, metal7, metal8) not found!")
     # Exit or handle error appropriately
     exit()

# Set offset for all PDN structures to 0
offset_um = 0
offset = [design.micronToDBU(offset_um) for i in range(4)]
pad_offset = [design.micronToDBU(offset_um) for i in range(4)]
# Set via cut pitch to 0
cut_pitch_um = 0
cut_pitch_x = design.micronToDBU(cut_pitch_um)
cut_pitch_y = design.micronToDBU(cut_pitch_um)

# Create core power grid structure
print("Creating core power grid...")
for domain in domains:
    # Create the main core grid structure
    pdngen.makeCoreGrid(domain = domain,
                        name = "core_grid",
                        starts_with = pdn.GROUND, # Start with ground net
                        pin_layers = [],
                        generate_obstructions = [],
                        powercell = None,
                        powercontrol = None,
                        powercontrolnetwork = "STAR")

# Configure and create core grid rings and straps
grid = pdngen.findGrid("core_grid")
if grid:
    for g in grid:
        # Power rings on M7 and M8
        ring_width_um = 5.0
        ring_spacing_um = 5.0
        print(f"Creating core power rings on M7 and M8 with width/spacing {ring_width_um} um...")
        pdngen.makeRing(grid = g,
                        layer0 = m7,
                        width0 = design.micronToDBU(ring_width_um),
                        spacing0 = design.micronToDBU(ring_spacing_um),
                        layer1 = m8,
                        width1 = design.micronToDBU(ring_width_um),
                        spacing1 = design.micronToDBU(ring_spacing_um),
                        starts_with = pdn.GRID,
                        offset = offset,
                        pad_offset = pad_offset,
                        extend = True, # Extend to boundary for rings
                        pad_pin_layers = [], # No specific pad layers needed for core ring
                        nets = [])

        # Horizontal power straps on metal1 (follow pin for standard cells)
        m1_width_um = 0.07
        print(f"Creating M1 followpin straps with width {m1_width_um} um...")
        pdngen.makeFollowpin(grid = g,
                             layer = m1,
                             width = design.micronToDBU(m1_width_um),
                             extend = pdn.CORE) # Extend within the core boundary

        # Power straps on metal4
        m4_width_um = 1.2
        m4_spacing_um = 1.2
        m4_pitch_um = 6.0
        print(f"Creating M4 straps with width {m4_width_um} um, spacing {m4_spacing_um} um, pitch {m4_pitch_um} um...")
        pdngen.makeStrap(grid = g,
                         layer = m4,
                         width = design.micronToDBU(m4_width_um),
                         spacing = design.micronToDBU(m4_spacing_um),
                         pitch = design.micronToDBU(m4_pitch_um),
                         offset = offset[0], # Use x-offset
                         number_of_straps = 0, # Auto-calculate
                         snap = False, # Do not snap to grid
                         starts_with = pdn.GRID,
                         extend = pdn.CORE, # Extend within the core boundary
                         nets = [])

        # Power straps on metal7 and metal8
        m7m8_width_um = 1.4
        m7m8_spacing_um = 1.4
        m7m8_pitch_um = 10.8
        print(f"Creating M7/M8 straps with width {m7m8_width_um} um, spacing {m7m8_spacing_um} um, pitch {m7m8_pitch_um} um...")
        pdngen.makeStrap(grid = g,
                         layer = m7,
                         width = design.micronToDBU(m7m8_width_um),
                         spacing = design.micronToDBU(m7m8_spacing_um),
                         pitch = design.micronToDBU(m7m8_pitch_um),
                         offset = offset[0], # Use x-offset
                         number_of_straps = 0, # Auto-calculate
                         snap = False, # Do not snap to grid
                         starts_with = pdn.GRID,
                         extend = pdn.RINGS, # Extend to the power rings
                         nets = [])
        pdngen.makeStrap(grid = g,
                         layer = m8,
                         width = design.micronToDBU(m7m8_width_um),
                         spacing = design.micronToDBU(m7m8_spacing_um),
                         pitch = design.micronToDBU(m7m8_pitch_um),
                         offset = offset[1], # Use y-offset
                         number_of_straps = 0, # Auto-calculate
                         snap = False, # Do not snap to grid
                         starts_with = pdn.GRID,
                         extend = pdn.RINGS, # Extend to the power rings
                         nets = [])


        # Create via connections for core grid
        print("Creating core grid via connections...")
        pdngen.makeConnect(grid = g, layer0 = m1, layer1 = m4, cut_pitch_x = cut_pitch_x, cut_pitch_y = cut_pitch_y, vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
        pdngen.makeConnect(grid = g, layer0 = m4, layer1 = m7, cut_pitch_x = cut_pitch_x, cut_pitch_y = cut_pitch_y, vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
        pdngen.makeConnect(grid = g, layer0 = m7, layer1 = m8, cut_pitch_x = cut_pitch_x, cut_pitch_y = cut_pitch_y, vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")

# Create power grid for macro blocks if present
if len(macros) > 0:
    print(f"Creating PDN for {len(macros)} macros...")
    # Halo is already handled by makeInstanceGrid if pg_pins_to_boundary is False
    macro_halo = [design.micronToDBU(0) for i in range(4)] # Set halo to 0 for makeInstanceGrid as we added halo during macro placement

    for i, macro_inst in enumerate(macros):
        # Create separate power grid for each macro instance
        for domain in domains:
            pdngen.makeInstanceGrid(domain = domain,
                                    name = f"macro_grid_{i}",
                                    starts_with = pdn.GROUND,
                                    inst = macro_inst,
                                    halo = macro_halo,
                                    pg_pins_to_boundary = False, # Let straps handle pin connection
                                    default_grid = False,
                                    generate_obstructions = [],
                                    is_bump = False)

        macro_grid = pdngen.findGrid(f"macro_grid_{i}")
        if macro_grid:
            for mg in macro_grid:
                # Power straps on metal5 and metal6 for macro connections
                m5m6_width_um = 1.2
                m5m6_spacing_um = 1.2
                m5m6_pitch_um = 6.0
                print(f"Creating M5/M6 straps for macro {macro_inst.getName()} with width {m5m6_width_um} um, spacing {m5m6_spacing_um} um, pitch {m5m6_pitch_um} um...")
                pdngen.makeStrap(grid = mg,
                                 layer = m5,
                                 width = design.micronToDBU(m5m6_width_um),
                                 spacing = design.micronToDBU(m5m6_spacing_um),
                                 pitch = design.micronToDBU(m5m6_pitch_um),
                                 offset = offset[0], # Use x-offset
                                 number_of_straps = 0, # Auto-calculate
                                 snap = True, # Snap to grid for macros
                                 starts_with = pdn.GRID,
                                 extend = pdn.CORE, # Extend within the macro instance grid boundary
                                 nets = [])
                pdngen.makeStrap(grid = mg,
                                 layer = m6,
                                 width = design.micronToDBU(m5m6_width_um),
                                 spacing = design.micronToDBU(m5m6_spacing_um),
                                 pitch = design.micronToDBU(m5m6_pitch_um),
                                 offset = offset[1], # Use y-offset
                                 number_of_straps = 0, # Auto-calculate
                                 snap = True, # Snap to grid for macros
                                 starts_with = pdn.GRID,
                                 extend = pdn.CORE, # Extend within the macro instance grid boundary
                                 nets = [])

                # Create via connections between macro power grid layers and core grid
                print("Creating macro grid via connections...")
                # Connect M4 (core grid) to M5 (macro grid)
                pdngen.makeConnect(grid = mg, layer0 = m4, layer1 = m5, cut_pitch_x = cut_pitch_x, cut_pitch_y = cut_pitch_y, vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
                # Connect M5 to M6 (macro grid layers)
                pdngen.makeConnect(grid = mg, layer0 = m5, layer1 = m6, cut_pitch_x = cut_pitch_x, cut_pitch_y = cut_pitch_y, vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
                # Connect M6 (macro grid) to M7 (core grid)
                pdngen.makeConnect(grid = mg, layer0 = m6, layer1 = m7, cut_pitch_x = cut_pitch_x, cut_pitch_y = cut_pitch_y, vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")


# Verify and build the final power delivery network
print("Building and writing PDN...")
pdngen.checkSetup() # Verify configuration
pdngen.buildGrids(False) # Build the power grid
pdngen.writeToDb(True) # Write power grid shapes to the design database
pdngen.resetShapes() # Reset temporary shapes

# Write DEF with PDN
print("Writing PDN DEF...")
design.writeDef("pdn.def")


# Configure and run global routing
print("Running global routing...")
grt = design.getGlobalRouter()

# Set routing layer ranges for signal and clock nets
# Find routing levels for metal1 and metal7
signal_low_layer = m1.getRoutingLevel()
signal_high_layer = m7.getRoutingLevel()
clk_low_layer = m1.getRoutingLevel()
clk_high_layer = m7.getRoutingLevel()

print(f"Setting signal routing layers: {signal_low_layer} to {signal_high_layer}")
print(f"Setting clock routing layers: {clk_low_layer} to {clk_high_layer}")
grt.setMinRoutingLayer(signal_low_layer)
grt.setMaxRoutingLayer(signal_high_layer)
grt.setMinLayerForClock(clk_low_layer)
grt.setMaxLayerForClock(clk_high_layer)

grt.setAdjustment(0.5) # Example congestion adjustment
grt.setVerbose(True)
grt.setIterations(30) # Set global router iterations to 30
print(f"Running global routing for {grt.getIterations()} iterations...")
grt.globalRoute(True) # Run global routing

# Write global routed DEF
print("Writing global routed DEF...")
design.writeDef("global_routed.def")

# Configure and run detailed routing
print("Running detailed routing...")
drter = design.getTritonRoute()
params = drt.ParamStruct()

# Set detailed routing parameters
params.outputMazeFile = ""
params.outputDrcFile = ""
params.outputCmapFile = ""
params.outputGuideCoverageFile = ""
params.dbProcessNode = "" # Set process node if needed (e.g., "12nm")
params.enableViaGen = True
params.drouteEndIter = 1 # Number of detailed routing iterations
params.viaInPinBottomLayer = ""
params.viaInPinTopLayer = ""
params.orSeed = -1
params.orK = 0
# Set detailed routing layer range (M1 to M7)
params.bottomRoutingLayer = "metal1"
params.topRoutingLayer = "metal7"
params.verbose = 1
params.cleanPatches = True # Clean up routing patches
params.doPa = True # Perform post-route repair
params.singleStepDR = False
params.minAccessPoints = 1
params.saveGuideUpdates = False

# Apply parameters and run detailed routing
drter.setParams(params)
drter.main()

# Write detailed routed DEF
print("Writing detailed routed DEF...")
design.writeDef("detailed_routed.def")

# Write final Verilog netlist (post-routing)
print("Writing final Verilog netlist...")
design.evalTclString("write_verilog final.v")

print("Physical design flow completed.")