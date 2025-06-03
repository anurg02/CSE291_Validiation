from openroad import Tech, Design, Timing
from pathlib import Path
import odb
import pdn
import drt
import psm

# Initialize OpenROAD objects and read technology files
tech = Tech()

# Get the database object from the tech object
db = tech.getDB()

# Set paths to library and design files
libDir = Path("../Design/nangate45/lib") # Assuming this path structure
lefDir = Path("../Design/nangate45/lef") # Assuming this path structure
designDir = Path("../Design/") # Assuming this path structure

# Define design parameters
# Assuming 'gcd' is the top module based on common OpenROAD examples
design_top_module_name = "gcd"
clock_port_name = "clk_i"
clock_period_ns = 40
clock_name = "core_clock"

# Read all liberty (.lib) and LEF files from the library directories
libFiles = list(libDir.glob("*.lib"))
techLefFiles = list(lefDir.glob("*.tech.lef"))
lefFiles = list(lefDir.glob('*.lef'))

# Load liberty timing libraries
print("Reading liberty files...")
for libFile in libFiles:
    print(f"Reading {libFile}")
    tech.readLiberty(libFile.as_posix())
print("Finished reading liberty files.")

# Load technology and cell LEF files
print("Reading LEF files...")
for techLefFile in techLefFiles:
    print(f"Reading {techLefFile}")
    tech.readLef(techLefFile.as_posix())
for lefFile in lefFiles:
    print(f"Reading {lefFile}")
    tech.readLef(lefFile.as_posix())
print("Finished reading LEF files.")

# Create design and read Verilog netlist
design = Design(tech)
verilogFile = designDir/str(design_top_module_name + ".v") # Assuming verilog file name matches top module
print(f"Reading Verilog file: {verilogFile}")
design.readVerilog(verilogFile.as_posix())
print(f"Linking design: {design_top_module_name}")
design.link(design_top_module_name)
print("Design linked.")

# Configure clock constraints
# Create clock with specified period and name on the clk_i port (API 2)
print(f"Creating clock '{clock_name}' on port '{clock_port_name}' with period {clock_period_ns} ns")
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
# Propagate the defined clock signal (API 10)
print("Setting propagated clock...")
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")
print("Propagated clock set.")

# Initialize floorplan with core area defined by utilization, aspect ratio, and margin
print("Starting floorplanning...")
floorplan = design.getFloorplan()
# Find the site definition from the loaded LEF files (assuming a common site from examples)
# Note: The site name might vary depending on the specific LEF files.
# A robust script might iterate through library sites to find a suitable one.
# Using a placeholder name here. You might need to replace this with the actual site name.
site_name = "FreePDK45_38x28_10R_NP_162NW_34O" # Placeholder - **VERIFY THIS SITE NAME IN YOUR LEF**
site = floorplan.findSite(site_name)
if site is None:
    print(f"ERROR: Site '{site_name}' not found. Please update the script with the correct site name from your LEF files.")
    # Example of how to find a site if the name is unknown:
    # for lib in db.getLibs():
    #     for s in lib.getSites():
    #         print(f"Found site: {s.getName()}")
    #         if "core" in s.getName().lower() or "stdcell" in s.getName().lower(): # Heuristic search
    #              site = s
    #              print(f"Using site: {site.getName()}")
    #              break
    #     if site: break
    # if site is None:
    #     print("Could not find any site in the libraries.")
    #     exit() # Or handle error appropriately

utilization = 0.45
aspect_ratio = 1.0 # Assuming aspect ratio 1.0
margin_micron = 10
leftSpace = design.micronToDBU(margin_micron)
rightSpace = design.micronToDBU(margin_micron)
topSpace = design.micronToDBU(margin_micron)
bottomSpace = design.micronToDBU(margin_micron)
# Initialize floorplan using utilization, aspect ratio, and margins
print(f"Initializing floorplan with utilization={utilization}, aspect_ratio={aspect_ratio}, core-to-die margin={margin_micron} um...")
floorplan.initFloorplan(utilization, aspect_ratio, bottomSpace, topSpace, leftSpace, rightSpace, site)
# Create placement tracks based on the floorplan and site
print("Creating placement tracks...")
floorplan.makeTracks()
print("Floorplan and tracks created.")

# Configure and run I/O pin placement
print("Starting I/O pin placement...")
iop = design.getIOPlacer()
params = iop.getParameters()
params.setRandSeed(42) # Set random seed for reproducible placement
params.setMinDistanceInTracks(False) # Use DBU for min distance, not tracks
params.setMinDistance(design.micronToDBU(0)) # Minimum distance between pins
params.setCornerAvoidance(design.micronToDBU(0)) # Distance to avoid corners
# Add metal layers for horizontal and vertical pin placement
m8 = db.getTech().findLayer("metal8")
m9 = db.getTech().findLayer("metal9")
if m8 is None or m9 is None:
     print("ERROR: metal8 or metal9 layer not found. Cannot place pins.")
else:
    # Determine layer directions to assign horizontal/vertical
    if m8.getDirection().getName() == "HORIZONTAL":
        iop.addHorLayer(m8)
        iop.addVerLayer(m9)
    else: # Assuming M9 is horizontal if M8 is not
        iop.addHorLayer(m9)
        iop.addVerLayer(m8)

    # Run IO placement using simulated annealing
    IOPlacer_random_mode = True # Use random mode for annealing
    iop.runAnnealing(IOPlacer_random_mode)
    print("I/O pin placement finished.")


# Place macro blocks if present
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
if len(macros) > 0:
    print(f"Found {len(macros)} macros. Starting macro placement...")
    mpl = design.getMacroPlacer()
    # Define the macro placement bounding box in microns
    bbox_lx_micron = 32
    bbox_ly_micron = 32
    bbox_ux_micron = 55
    bbox_uy_micron = 60

    # Configure and run macro placement within the specified bounding box (fence)
    mpl.place(
        num_threads = 4, # Number of threads
        halo_width = 5.0, # Halo width around macros (in microns)
        halo_height = 5.0, # Halo height around macros (in microns)
        min_macro_macro_dist_x = design.micronToDBU(5), # Minimum distance between macros in X (in DBU)
        min_macro_macro_dist_y = design.micronToDBU(5), # Minimum distance between macros in Y (in DBU)
        # Set the fence region to the specified bounding box in microns
        fence_lx = bbox_lx_micron,
        fence_ly = bbox_ly_micron,
        fence_ux = bbox_ux_micron,
        fence_uy = bbox_uy_micron,
        # Other parameters from examples, adjust or use defaults as needed
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
        target_util = 0.25, # Target utilization within fence (adjust if needed)
        target_dead_space = 0.05, # Target dead space within fence
        min_ar = 0.33,
        bus_planning_flag = False,
        report_directory = ""
    )
    print("Macro placement finished.")
else:
    print("No macros found. Skipping macro placement.")


# Configure and run global placement (Standard Cells)
print("Starting global placement...")
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Not timing driven as per prompt context (no timing analysis requested yet)
gpl.setRoutabilityDrivenMode(True) # Routability driven
gpl.setUniformTargetDensityMode(True) # Uniform target density
# Set the number of initial placement iterations (interpretation of "global router iteration")
global_place_iterations = 30
gpl.setInitialPlaceMaxIter(global_place_iterations)
gpl.setInitDensityPenalityFactor(0.05) # Initial density penalty factor
gpl.doInitialPlace(threads = 4) # Run initial placement
gpl.doNesterovPlace(threads = 4) # Run Nesterov-based placement
gpl.reset() # Reset placer state
print("Global placement finished.")


# Run detailed placement
print("Starting detailed placement...")
dp = design.getOpendp()
# Set maximum displacement allowed in X and Y directions (0um in this case)
max_disp_x_micron = 0
max_disp_y_micron = 0
max_disp_x_dbu = design.micronToDBU(max_disp_x_micron)
max_disp_y_dbu = design.micronToDBU(max_disp_y_micron)
# Remove any existing filler cells before placement (good practice)
dp.removeFillers()
# Perform detailed placement with specified max displacement (0 displacement in this case)
print(f"Running detailed placement with max displacement {max_disp_x_micron} um X, {max_disp_y_micron} um Y...")
dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Detailed placement finished.")


# Configure and run clock tree synthesis (CTS)
print("Starting CTS...")
# Set propagated clock (should be already set after create_clock, but reaffirm) (API 10)
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")
# Set unit resistance and capacitance values for clock and signal nets (API 1)
unit_resistance = 0.0435
unit_capacitance = 0.0817
print(f"Setting wire RC for clock and signal nets (R={unit_resistance}, C={unit_capacitance})...")
design.evalTclString(f"set_wire_rc -clock -resistance {unit_resistance} -capacitance {unit_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {unit_resistance} -capacitance {unit_capacitance}")
# Get the TritonCTS module (API 6)
cts = design.getTritonCts()
parms = cts.getParms()
parms.setWireSegmentUnit(20) # Set wire segment unit length for CTS (example value)
# Configure clock buffers to use BUF_X3 (API 11)
buffer_cell = "BUF_X3" # **VERIFY THIS CELL NAME EXISTS IN YOUR LIBRARY**
print(f"Setting CTS buffers to '{buffer_cell}'...")
cts.setBufferList(buffer_cell)
cts.setRootBuffer(buffer_cell)
cts.setSinkBuffer(buffer_cell)
# Run Clock Tree Synthesis (API 5)
print("Running TritonCTS...")
cts.runTritonCts()
print("CTS finished.")


# Configure power delivery network (PDN)
print("Starting PDN construction...")
# Set up global power/ground connections - Done earlier, reaffirming nets
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")
if VDD_net is None or VSS_net is None:
    print("ERROR: VDD or VSS net not found. Cannot proceed with PDN.")
    # Exit or handle error appropriately
else:
    # Configure power domains
    pdngen = design.getPdnGen()
    domains = [pdngen.findDomain("Core")] # Assuming only one core domain

    # Define parameters from prompt
    # Core grid (Standard cells)
    m1_stdcell_width_micron = 0.07
    m7_ring_width_micron = 5
    m7_ring_spacing_micron = 5
    m8_ring_width_micron = 5
    m8_ring_spacing_micron = 5

    # Macro grid (if macros exist)
    m4_macro_width_micron = 1.2
    m4_macro_spacing_micron = 1.2
    m4_macro_pitch_micron = 6
    m5_macro_width_micron = 1.2
    m5_macro_spacing_micron = 1.2
    m5_macro_pitch_micron = 6
    m6_macro_width_micron = 1.2
    m6_macro_spacing_micron = 1.2
    m6_macro_pitch_micron = 6

    # Vias
    via_cut_pitch_micron = 2
    pdn_cut_pitch_x = design.micronToDBU(via_cut_pitch_micron)
    pdn_cut_pitch_y = design.micronToDBU(via_cut_pitch_micron)

    # Offset
    offset_micron = 0
    zero_offset_dbu = [design.micronToDBU(offset_micron) for i in range(4)]

    # Get routing layers
    m1 = db.getTech().findLayer("metal1")
    m4 = db.getTech().findLayer("metal4")
    m5 = db.getTech().findLayer("metal5")
    m6 = db.getTech().findLayer("metal6")
    m7 = db.getTech().findLayer("metal7")
    m8 = db.getTech().findLayer("metal8")

    # Check if necessary layers exist
    required_layers = {"metal1": m1, "metal4": m4, "metal5": m5, "metal6": m6, "metal7": m7, "metal8": m8}
    missing_layers = [name for name, layer in required_layers.items() if layer is None]
    if missing_layers:
        print(f"ERROR: Missing required PDN layers: {', '.join(missing_layers)}. Cannot proceed with PDN.")
    else:
        # --- Create Core Power Grid (for Standard Cells) ---
        core_grid_name = "core_stdcell_grid"
        print(f"Creating core grid '{core_grid_name}'...")
        pdngen.makeCoreGrid(domain = domains[0],
            name = core_grid_name,
            starts_with = pdn.GROUND, # Common practice, connect VSS first
            pin_layers = [],
            generate_obstructions = [],
            powercell = None,
            powercontrol = None,
            powercontrolnetwork = "STAR")

        core_grid = pdngen.findGrid(core_grid_name)[0]

        # Add power rings on metal7 and metal8 around the core
        print("Adding M7 and M8 power rings...")
        pdngen.makeRing(grid = core_grid,
            layer0 = m7,
            width0 = design.micronToDBU(m7_ring_width_micron),
            spacing0 = design.micronToDBU(m7_ring_spacing_micron),
            layer1 = m8,
            width1 = design.micronToDBU(m8_ring_width_micron),
            spacing1 = design.micronToDBU(m8_ring_spacing_micron),
            starts_with = pdn.GRID,
            offset = zero_offset_dbu,
            pad_offset = zero_offset_dbu,
            extend = False,
            pad_pin_layers = [],
            nets = [],
            allow_out_of_die = True)

        # Add horizontal power straps on metal1 (followpin) for standard cells
        print("Adding M1 followpin straps for standard cells...")
        pdngen.makeFollowpin(grid = core_grid,
            layer = m1,
            width = design.micronToDBU(m1_stdcell_width_micron),
            extend = pdn.CORE)


        # --- Create Power Grids for Macro Blocks if they exist ---
        macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
        if len(macros) > 0:
            print(f"Adding instance grids for {len(macros)} macros...")
            # Halo for macro instance grid - 0 offset as per requirement
            halo_macro_inst = [design.micronToDBU(offset_micron) for i in range(4)]

            for i, macro_inst in enumerate(macros):
                macro_grid_name = f"macro_grid_{i}"
                print(f"Creating instance grid '{macro_grid_name}' for macro '{macro_inst.getName()}'...")
                # Create separate high-level PDN grid for each macro instance (API 16)
                pdngen.makeInstanceGrid(domain = domains[0], # Associate with the core domain
                    name = macro_grid_name,
                    starts_with = pdn.GRID,
                    inst = macro_inst,
                    halo = halo_macro_inst, # 0um halo
                    pg_pins_to_boundary = True,  # Connect power/ground pins to boundary
                    default_grid = False,
                    generate_obstructions = [],
                    is_bump = False)

                macro_grid = pdngen.findGrid(macro_grid_name)[0] # Assuming one grid per instance

                # Add power straps on metal4 for macro connections
                print(f"  Adding M4 straps to '{macro_grid_name}'...")
                pdngen.makeStrap(grid = macro_grid,
                    layer = m4,
                    width = design.micronToDBU(m4_macro_width_micron),
                    spacing = design.micronToDBU(m4_macro_spacing_micron),
                    pitch = design.micronToDBU(m4_macro_pitch_micron),
                    offset = design.micronToDBU(offset_micron),
                    number_of_straps = 0,
                    snap = True,
                    starts_with = pdn.GRID,
                    extend = pdn.NONE, # Extend within the instance grid definition area
                    nets = [])

                # Add power straps on metal5 for macro connections
                print(f"  Adding M5 straps to '{macro_grid_name}'...")
                pdngen.makeStrap(grid = macro_grid,
                    layer = m5,
                    width = design.micronToDBU(m5_macro_width_micron),
                    spacing = design.micronToDBU(m5_macro_spacing_micron),
                    pitch = design.micronToDBU(m5_macro_pitch_micron),
                    offset = design.micronToDBU(offset_micron),
                    number_of_straps = 0,
                    snap = True,
                    starts_with = pdn.GRID,
                    extend = pdn.NONE,
                    nets = [])

                # Add power straps on metal6 for macro connections
                print(f"  Adding M6 straps to '{macro_grid_name}'...")
                pdngen.makeStrap(grid = macro_grid,
                    layer = m6,
                    width = design.micronToDBU(m6_macro_width_micron),
                    spacing = design.micronToDBU(m6_macro_spacing_micron),
                    pitch = design.micronToDBU(m6_macro_pitch_micron),
                    offset = design.micronToDBU(offset_micron),
                    number_of_straps = 0,
                    snap = True,
                    starts_with = pdn.GRID,
                    extend = pdn.NONE,
                    nets = [])
        else:
            print("No macros found. Skipping macro PDN construction.")


        # --- Create Via Connections (2um cut pitch) ---
        print("Adding via connections (2um cut pitch)...")
        # Vias within Core Grid: M1-M7, M7-M8
        print("  Adding vias within core grid (M1-M7, M7-M8)...")
        pdngen.makeConnect(grid = core_grid, layer0 = m1, layer1 = m7,
            cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y)
        pdngen.makeConnect(grid = core_grid, layer0 = m7, layer1 = m8,
            cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y)

        # Vias within Macro Instance Grids and connecting to Core Grid
        if len(macros) > 0:
            for i, macro_inst in enumerate(macros):
                macro_grid = pdngen.findGrid(f"macro_grid_{i}")[0]
                print(f"  Adding vias for macro grid '{macro_grid.getName()}' (M4-M5, M5-M6, M6-M7)...")
                # Within macro grid: M4-M5, M5-M6
                pdngen.makeConnect(grid = macro_grid, layer0 = m4, layer1 = m5,
                    cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y)
                pdngen.makeConnect(grid = macro_grid, layer0 = m5, layer1 = m6,
                    cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y)
                # Connect Macro Grid (M6) to Core Grid (M7)
                pdngen.makeConnect(grid = macro_grid, layer0 = m6, layer1 = m7,
                    cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y)


        # Generate the final power delivery network
        print("Building and writing PDN to DB...")
        pdngen.checkSetup()  # Verify configuration
        pdngen.buildGrids(False)  # Build the power grid (False means without obstacles)
        pdngen.writeToDb(True)  # Write power grid shapes to the design database
        pdngen.resetShapes()  # Reset temporary shapes after writing
        print("PDN construction finished.")


# Insert filler cells (standard practice after placement/PDN)
print("Inserting filler cells...")
# Filler cells are inserted to fill empty spaces in the placement rows
db = design.getTech().getDB() # Get the database object
filler_masters = list()
# Collect all masters that are defined as CORE_SPACER type
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)
# Perform filler placement if filler cells are found
if len(filler_masters) == 0:
    print("No filler cells found in library.")
else:
    # filler cells' naming convention prefix
    filler_cells_prefix = "FILLCELL_"
    design.getOpendp().fillerPlacement(filler_masters = filler_masters,
                                     prefix = filler_cells_prefix,
                                     verbose = False)
    print("Filler cell placement finished.")


# Configure and run global routing
print("Starting global routing...")
# Set routing layer ranges for signal and clock nets (using M1-M7 as in examples)
m1_routing_level = m1.getRoutingLevel() if m1 else 1
m7_routing_level = m7.getRoutingLevel() if m7 else 7

signal_low_layer = m1_routing_level
signal_high_layer = m7_routing_level
clk_low_layer = m1_routing_level # API 3
clk_high_layer = m7_routing_level # API 4

grt = design.getGlobalRouter()
grt.setMinRoutingLayer(signal_low_layer)
grt.setMaxRoutingLayer(signal_high_layer)
grt.setMinLayerForClock(clk_low_layer)
grt.setMaxLayerForClock(clk_high_layer)
grt.setAdjustment(0.5) # Set routing congestion adjustment (example value)
grt.setVerbose(True)
grt.globalRoute(True) # Run global routing (True often implies timing-driven, adjust if needed)
print("Global routing finished.")


# Configure and run detailed routing
print("Starting detailed routing...")
drter = design.getTritonRoute()
params = drt.ParamStruct()
# Set routing layer range for detailed router (using M1-M7)
params.bottomRoutingLayer = "metal1" if m1 else ""
params.topRoutingLayer = "metal7" if m7 else ""
params.verbose = 1
params.cleanPatches = True
params.doPa = True # Perform post-route antenna fixing
params.singleStepDR = False # Run detailed routing in multiple steps (example)
params.drouteEndIter = 1 # Number of detailed routing iterations (example)
# Other parameters from example, use defaults or adjust as needed
params.outputMazeFile = ""
params.outputDrcFile = ""
params.outputCmapFile = ""
params.outputGuideCoverageFile = ""
params.dbProcessNode = ""
params.enableViaGen = True
params.viaInPinBottomLayer = "" # Optional, specify layers for via-in-pin
params.viaInPinTopLayer = ""   # Optional
params.orSeed = -1
params.orK = 0
params.minAccessPoints = 1
params.saveGuideUpdates = False

drter.setParams(params)
if params.bottomRoutingLayer and params.topRoutingLayer:
    drter.main() # Run detailed routing
    print("Detailed routing finished.")
else:
     print("Skipping detailed routing due to missing layers.")


# Run static IR drop analysis
print("Starting IR drop analysis...")
psm_obj = design.getPDNSim()
timing = Timing(design) # Get timing object for corner
# Specify the target net for analysis (VDD)
target_net = design.getBlock().findNet("VDD")
if target_net is None:
    print("ERROR: VDD net not found for IR drop analysis.")
else:
    # Set analysis parameters
    # GeneratedSourceType_FULL places sources at standard cell locations
    source_types = [psm.GeneratedSourceType_FULL]
    # Analyze VDD power grid (API 19 takes net)
    # Note: This analyzes the full VDD grid. Getting results specifically "on M1 layer" usually involves
    # parsing the analysis report or accessing specific PSM result objects after the run,
    # which is not directly exposed as a simple return value here. The analysis is performed
    # on the entire grid structure.
    try:
        psm_obj.analyzePowerGrid(net = target_net,
            enable_em = False, # Disable electromigration analysis
            corner = timing.getCorners()[0], # Use the first timing corner
            use_prev_solution = False,
            em_file = "",
            error_file = "",
            voltage_source_file = "",
            voltage_file = "",
            source_type = source_types[0])
        print("IR drop analysis finished.")
        # Results would typically be viewed in the OpenROAD GUI or parsed from generated files.
    except Exception as e:
        print(f"ERROR during IR drop analysis: {e}")


# Save final DEF file with the requested name
output_def_filename = "PDN.def"
print(f"Writing output DEF file: {output_def_filename}...")
design.writeDef(output_def_filename)
print("Script finished.")