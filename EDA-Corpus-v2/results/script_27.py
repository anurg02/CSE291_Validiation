# Imports
import openroad as ord
from openroad import Tech, Design, Timing
from pathlib import Path
import odb
import pdn
import drt
import psm

# Define paths and filenames (placeholders)
# !!! User must replace these paths with actual paths to their files !!!
libDir = Path("../Design/nangate45/lib") # Example library directory
lefDir = Path("../Design/nangate45/lef") # Example LEF directory
designDir = Path("../Design/")          # Example design directory
verilogFile = designDir / "mydesign.v"   # Example Verilog file name
design_top_module_name = "mydesign"      # Example top module name
site_name = "FreePDK45_38x28_10R_NP_162NW_34O" # Example standard cell site name

# Initialize OpenROAD objects and read technology files
tech = Tech()

# Read all liberty (.lib) and LEF files
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
design.readVerilog(verilogFile.as_posix())
# Link the design to the libraries and technology
design.link(design_top_module_name)

# Configure clock constraints
clock_period_ns = 40.0
clock_port_name = "clk"
clock_name = "core_clock"
# Create a clock signal on the specified port with the given period and name
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
# Set the created clock as the propagated timing clock
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Initialize floorplan
floorplan = design.getFloorplan()

# Define die area in microns
die_lx_micron, die_ly_micron, die_ux_micron, die_uy_micron = 0.0, 0.0, 60.0, 50.0
# Define core area in microns
core_lx_micron, core_ly_micron, core_ux_micron, core_uy_micron = 8.0, 8.0, 52.0, 42.0
# Convert micron coordinates to DBU (Database Units)
die_area = odb.Rect(
    design.micronToDBU(die_lx_micron),
    design.micronToDBU(die_ly_micron),
    design.micronToDBU(die_ux_micron),
    design.micronToDBU(die_uy_micron)
)
core_area = odb.Rect(
    design.micronToDBU(core_lx_micron),
    design.micronToDBU(core_ly_micron),
    design.micronToDBU(core_ux_micron),
    design.micronToDBU(core_uy_micron)
)

# Find the standard cell site by name
site = floorplan.findSite(site_name)
if site is None:
    print(f"Error: Site '{site_name}' not found.")
    exit()

# Initialize the floorplan with die and core areas and create routing tracks based on the site
floorplan.initFloorplan(die_area, core_area, site)
floorplan.makeTracks()

# Identify macro instances in the design
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

# Configure and run macro placement if macros exist
if len(macros) > 0:
    mpl = design.getMacroPlacer()
    # Define macro placement fence region in microns
    fence_lx_micron, fence_ly_micron, fence_ux_micron, fence_uy_micron = 18.0, 12.0, 43.0, 42.0
    # Define macro halo in microns (space kept clear around the macro)
    macro_halo_width_micron = 5.0
    macro_halo_height_micron = 5.0

    # Place macros with the specified halo and fence region
    # Note: Min distance between macros (5um) is often controlled by the halo/fence and the placer's internal logic.
    # The parameters below configure the macro placer's behavior.
    mpl.place(
        num_threads = 64,
        max_num_macro = len(macros), # Consider all identified macros
        min_num_macro = 0,
        max_num_inst = 0, # Do not place standard cells using this placer
        min_num_inst = 0,
        tolerance = 0.1,
        max_num_level = 2,
        coarsening_ratio = 10.0,
        large_net_threshold = 50,
        signature_net_threshold = 50,
        halo_width = macro_halo_width_micron, # Set macro halo width
        halo_height = macro_halo_height_micron, # Set macro halo height
        fence_lx = fence_lx_micron, # Set fence region left x-coordinate
        fence_ly = fence_ly_micron, # Set fence region lower y-coordinate
        fence_ux = fence_ux_micron, # Set fence region right x-coordinate
        fence_uy = fence_uy_micron, # Set fence region upper y-coordinate
        area_weight = 0.1,
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        pin_access_th = 0.0,
        target_util = 0.25,
        target_dead_space = 0.05,
        min_ar = 0.33,
        snap_layer = 4, # Example layer to snap macro origins/pins to
        bus_planning_flag = False,
        report_directory = ""
    )

# Configure and run global placement for standard cells
gpl = design.getReplace()
# Disable timing-driven placement for this stage
gpl.setTimingDrivenMode(False)
# Enable routability-driven placement
gpl.setRoutabilityDrivenMode(True)
# Use uniform target density across the core area
gpl.setUniformTargetDensityMode(True)
# Set the maximum initial placement iterations (related to overall flow, not just one step)
# Using 30 as specified, although this parameter's effect varies by placer implementation.
gpl.setInitialPlaceMaxIter(30)
gpl.setInitDensityPenalityFactor(0.05)
# Execute the initial placement phase
gpl.doInitialPlace(threads = 4)
# Execute the main Nesterov-based global placement phase
gpl.doNesterovPlace(threads = 4)
# Reset the placer state
gpl.reset()

# Run initial detailed placement after global placement
dp = design.getOpendp()
# Allow maximum displacement in microns, convert to DBU (Database Units)
max_disp_x_micron = 1.0
max_disp_y_micron = 3.0
max_disp_x_dbu = design.micronToDBU(max_disp_x_micron)
max_disp_y_dbu = design.micronToDBU(max_disp_y_micron)
# Execute detailed placement with displacement limits
dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

# Configure and build power delivery network (PDN)
pdngen = design.getPdnGen()

# Set up global power/ground connections
block = design.getBlock()
# Iterate through all nets in the design block
for net in block.getNets():
    # Set signal type for power and ground nets to 'special'
    if net.getSigType() == "POWER" or net.getSigType() == "GROUND":
        net.setSpecial()

# Find existing power and ground nets or create them if they don't exist
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

# Create VDD/VSS nets if they don't exist and set their signal types and special status
if VDD_net is None:
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSigType("POWER")
    VDD_net.setSpecial()
if VSS_net is None:
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSigType("GROUND")
    VSS_net.setSpecial()

# Connect standard cell power pins (assuming pin names VDD and VSS) to the global VDD/VSS nets
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VDD$", net=VDD_net, do_connect=True)
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VSS$", net=VSS_net, do_connect=True)
# Apply the global connections
block.globalConnect()

# Configure the core power domain using the main VDD and VSS nets
pdngen.setCoreDomain(power=VDD_net, switched_power=None, ground=VSS_net, secondary=list())

# Get routing layers by name for PDN construction
m1 = tech.getDB().getTech().findLayer("metal1")
m4 = tech.getDB().getTech().findLayer("metal4")
m5 = tech.getDB().getTech().findLayer("metal5")
m6 = tech.getDB().getTech().findLayer("metal6")
m7 = tech.getDB().getTech().findLayer("metal7")
m8 = tech.getDB().getTech().findLayer("metal8")

# Ensure all required layers were found
if not all([m1, m4, m5, m6, m7, m8]):
    print("Error: Required metal layers not found in technology LEF for PDN construction.")
    exit()

# Convert PDN dimensions from microns to DBU
std_cell_m1_width_dbu = design.micronToDBU(0.07)
std_cell_m4_width_dbu = design.micronToDBU(1.2)
std_cell_m4_spacing_dbu = design.micronToDBU(1.2)
std_cell_m4_pitch_dbu = design.micronToDBU(6.0)
std_cell_m7_width_dbu = design.micronToDBU(1.4)
std_cell_m7_spacing_dbu = design.micronToDBU(1.4)
std_cell_m7_pitch_dbu = design.micronToDBU(10.8)

ring_m7_width_dbu = design.micronToDBU(5.0)
ring_m7_spacing_dbu = design.micronToDBU(5.0)
ring_m8_width_dbu = design.micronToDBU(5.0)
ring_m8_spacing_dbu = design.micronToDBU(5.0)

macro_m5_width_dbu = design.micronToDBU(1.2)
macro_m5_spacing_dbu = design.micronToDBU(1.2)
macro_m5_pitch_dbu = design.micronToDBU(6.0)
macro_m6_width_dbu = design.micronToDBU(1.2)
macro_m6_spacing_dbu = design.micronToDBU(1.2)
macro_m6_pitch_dbu = design.micronToDBU(6.0)

pdn_offset_dbu = [design.micronToDBU(0) for _ in range(4)] # Zero offset for rings/straps
pdn_cut_pitch_dbu = [design.micronToDBU(0), design.micronToDBU(0)] # Zero pitch for via arrays (dense connection)

# Create the main core grid structure for standard cells
domains = [pdngen.findDomain("Core")] # Get the core domain
for domain in domains:
    pdngen.makeCoreGrid(domain=domain,
                        name="core_grid",
                        starts_with=pdn.GROUND, # Define which net the grid structure starts with (e.g., lowest y-coordinate strap)
                        pin_layers=[], # Layers for pin connections (optional)
                        generate_obstructions=[], # Layers to generate routing obstructions on
                        powercell=None, # Power switch cell (if used)
                        powercontrol=None, # Power control signal (if used)
                        powercontrolnetwork="STAR") # Power control network type (if used)

core_grid = pdngen.findGrid("core_grid")
if core_grid:
    # Add power rings on M7 and M8 around the core boundary
    pdngen.makeRing(grid=core_grid,
                    layer0=m7, width0=ring_m7_width_dbu, spacing0=ring_m7_spacing_dbu,
                    layer1=m8, width1=ring_m8_width_dbu, spacing1=ring_m8_spacing_dbu,
                    starts_with=pdn.GRID, # Alignment relative to the grid definition
                    offset=pdn_offset_dbu, # Offset from the target boundary (core)
                    pad_offset=pdn_offset_dbu, # Offset from pads (not used here)
                    extend=False, # Do not extend rings beyond the target boundary
                    pad_pin_layers=[], # No direct connection to pads from these rings
                    nets=[VDD_net, VSS_net]) # Nets associated with these rings

    # Add horizontal followpin straps on M1, following standard cell power rail pins
    pdngen.makeFollowpin(grid=core_grid,
                         layer=m1,
                         width=std_cell_m1_width_dbu,
                         extend=pdn.CORE) # Extend followpins across the core area

    # Add power straps on M4 with specified dimensions
    pdngen.makeStrap(grid=core_grid,
                     layer=m4,
                     width=std_cell_m4_width_dbu,
                     spacing=std_cell_m4_spacing_dbu,
                     pitch=std_cell_m4_pitch_dbu,
                     offset=design.micronToDBU(0), # Offset from grid start or boundary
                     number_of_straps=0, # Auto-calculate number of straps
                     snap=True, # Snap straps to manufacturing grid or site grid
                     starts_with=pdn.GRID, # Alignment relative to the grid definition
                     extend=pdn.CORE, # Extend straps across the core area
                     nets=[VDD_net, VSS_net])

    # Add power straps on M7 with specified dimensions
    pdngen.makeStrap(grid=core_grid,
                     layer=m7,
                     width=std_cell_m7_width_dbu,
                     spacing=std_cell_m7_spacing_dbu,
                     pitch=std_cell_m7_pitch_dbu,
                     offset=design.micronToDBU(0),
                     number_of_straps=0,
                     snap=True,
                     starts_with=pdn.GRID,
                     extend=pdn.RINGS, # Extend straps to connect to the M7/M8 rings
                     nets=[VDD_net, VSS_net])

    # Add power straps on M8 with specified dimensions (connecting to rings)
    # Assuming same width/spacing/pitch as M7 straps based on typical ring structure
    pdngen.makeStrap(grid=core_grid,
                     layer=m8,
                     width=std_cell_m7_width_dbu,
                     spacing=std_cell_m7_spacing_dbu,
                     pitch=std_cell_m7_pitch_dbu,
                     offset=design.micronToDBU(0),
                     number_of_straps=0,
                     snap=True,
                     starts_with=pdn.GRID,
                     extend=pdn.RINGS, # Extend straps to connect to the M7/M8 rings
                     nets=[VDD_net, VSS_net])


    # Create via connections between standard cell grid layers
    # Connect M1 followpins to M4 straps
    pdngen.makeConnect(grid=core_grid, layer0=m1, layer1=m4,
                       cut_pitch_x=pdn_cut_pitch_dbu[0], cut_pitch_y=pdn_cut_pitch_dbu[1],
                       vias=[], techvias=[], max_rows=0, max_columns=0, ongrid=[], split_cuts=dict(), dont_use_vias="")
    # Connect M4 straps to M7 straps/rings
    pdngen.makeConnect(grid=core_grid, layer0=m4, layer1=m7,
                       cut_pitch_x=pdn_cut_pitch_dbu[0], cut_pitch_y=pdn_cut_pitch_dbu[1],
                       vias=[], techvias=[], max_rows=0, max_columns=0, ongrid=[], split_cuts=dict(), dont_use_vias="")
    # Connect M7 straps/rings to M8 rings/straps
    pdngen.makeConnect(grid=core_grid, layer0=m7, layer1=m8,
                       cut_pitch_x=pdn_cut_pitch_dbu[0], cut_pitch_y=pdn_cut_pitch_dbu[1],
                       vias=[], techvias=[], max_rows=0, max_columns=0, ongrid=[], split_cuts=dict(), dont_use_vias="")


# Create power grids for macro instances if they exist
if len(macros) > 0:
    # Define halo around macros for instance grid creation
    macro_halo_dbu = [design.micronToDBU(5.0)] * 4
    macro_nets = [VDD_net, VSS_net] # Nets the macro grid belongs to

    for i, macro_inst in enumerate(macros):
        # Create a grid specifically for this macro instance
        for domain in domains: # Assuming macros are within the core domain
            pdngen.makeInstanceGrid(domain=domain,
                                    name=f"macro_grid_{i}", # Unique name for each macro grid
                                    starts_with=pdn.GROUND, # Define which net the macro grid starts with
                                    inst=macro_inst, # Associate grid with the specific macro instance
                                    halo=macro_halo_dbu, # Apply halo around macro for grid extent
                                    pg_pins_to_boundary=True, # Connect macro PG pins to the macro grid boundary
                                    default_grid=False, # This is not a default grid
                                    generate_obstructions=[],
                                    is_bump=False) # Not a bump grid

        macro_inst_grid = pdngen.findGrid(f"macro_grid_{i}")
        if macro_inst_grid:
            # Add power straps on M5 within the macro grid boundary
            pdngen.makeStrap(grid=macro_inst_grid,
                             layer=m5,
                             width=macro_m5_width_dbu,
                             spacing=macro_m5_spacing_dbu,
                             pitch=macro_m5_pitch_dbu,
                             offset=design.micronToDBU(0),
                             number_of_straps=0,
                             snap=True, # Snap straps to grid/manufacturing grid
                             starts_with=pdn.GRID,
                             extend=pdn.BOUNDARY, # Extend straps within the macro instance grid boundary (defined by halo)
                             nets=macro_nets)

            # Add power straps on M6 within the macro grid boundary
            pdngen.makeStrap(grid=macro_inst_grid,
                             layer=m6,
                             width=macro_m6_width_dbu,
                             spacing=macro_m6_spacing_dbu,
                             pitch=macro_m6_pitch_dbu,
                             offset=design.micronToDBU(0),
                             number_of_straps=0,
                             snap=True,
                             starts_with=pdn.GRID,
                             extend=pdn.BOUNDARY, # Extend straps within the macro instance grid boundary
                             nets=macro_nets)

            # Create via connections for macro grids, linking them to the core grid
            # Connect M4 (from core grid) to M5 (macro grid)
            pdngen.makeConnect(grid=macro_inst_grid, layer0=m4, layer1=m5,
                               cut_pitch_x=pdn_cut_pitch_dbu[0], cut_pitch_y=pdn_cut_pitch_dbu[1],
                               vias=[], techvias=[], max_rows=0, max_columns=0, ongrid=[], split_cuts=dict(), dont_use_vias="")
            # Connect M5 to M6 (macro grid layers)
            pdngen.makeConnect(grid=macro_inst_grid, layer0=m5, layer1=m6,
                               cut_pitch_x=pdn_cut_pitch_dbu[0], cut_pitch_y=pdn_cut_pitch_dbu[1],
                               vias=[], techvias=[], max_rows=0, max_columns=0, ongrid=[], split_cuts=dict(), dont_use_vias="")
            # Connect M6 (macro grid) to M7 (core grid)
            pdngen.makeConnect(grid=macro_inst_grid, layer0=m6, layer1=m7,
                               cut_pitch_x=pdn_cut_pitch_dbu[0], cut_pitch_y=pdn_cut_pitch_dbu[1],
                               vias=[], techvias=[], max_rows=0, max_columns=0, ongrid=[], split_cuts=dict(), dont_use_vias="")


# Verify and build the PDN
pdngen.checkSetup() # Verify the PDN configuration
pdngen.buildGrids(False) # Build the geometric shapes for the PDN grids in memory
pdngen.writeToDb(True, ) # Write the generated PDN shapes to the design database
pdngen.resetShapes() # Clear temporary shapes used during generation

# Configure and run clock tree synthesis (CTS)
cts = design.getTritonCts()
parms = cts.getParms()
parms.setWireSegmentUnit(20) # Example wire segment unit for clock tree

# Set the list of available clock buffers from the library
cts.setBufferList("BUF_X2")
# Set the clock buffer used at the root of the clock tree
cts.setRootBuffer("BUF_X2")
# Set the clock buffer used at the sinks (endpoints) of the clock tree
cts.setSinkBuffer("BUF_X2")

# Set unit resistance and capacitance for clock and signal nets for timing analysis
design.evalTclString("set_wire_rc -clock -resistance 0.03574 -capacitance 0.07516")
design.evalTclString("set_wire_rc -signal -resistance 0.03574 -capacitance 0.07516")

# Run the CTS engine to synthesize the clock tree
cts.runTritonCts()

# Run final detailed placement after CTS
# This step is often necessary to legalize the placement after CTS buffer insertion
dp = design.getOpendp()
# Allow maximum displacement in microns, convert to DBU
max_disp_x_micron = 1.0
max_disp_y_micron = 3.0
max_disp_x_dbu = design.micronToDBU(max_disp_x_micron)
max_disp_y_dbu = design.micronToDBU(max_disp_y_micron)
# Execute detailed placement with the specified displacement limits
dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

# Insert filler cells to fill empty spaces in standard cell rows
# Find standard cell filler masters in the loaded libraries
filler_masters = list()
filler_cells_prefix = "FILLCELL_" # Example prefix for filler cells (adapt if different)
db = ord.get_db() # Get the current OpenROAD database
for lib in db.getLibs():
    for master in lib.getMasters():
        # Assuming filler cells have the CORE_SPACER type
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

if len(filler_masters) == 0:
    print("Warning: No filler cells found in libraries. Skipping filler placement.")
else:
    # Perform filler cell insertion to fill gaps in rows
    dp.fillerPlacement(filler_masters = filler_masters,
                       prefix = filler_cells_prefix,
                       verbose = False)

# Configure and run global routing
grt = design.getGlobalRouter()

# Find routing layer levels for the specified metal layers
try:
    m1_level = tech.getDB().getTech().findLayer("metal1").getRoutingLevel()
    m7_level = tech.getDB().getTech().findLayer("metal7").getRoutingLevel()
except AttributeError:
    print("Error: Could not find routing level for metal1 or metal7. Cannot configure global router layers.")
    exit()

# Set the minimum and maximum routing layers for signal nets
grt.setMinRoutingLayer(m1_level)
grt.setMaxRoutingLayer(m7_level)
# Set the minimum and maximum routing layers for clock nets (often same as signal layers)
grt.setMinLayerForClock(m1_level)
grt.setMaxLayerForClock(m7_level)

# Set routing congestion adjustment parameter (value influences routing iterations/quality)
grt.setAdjustment(0.5) # Example adjustment value
grt.setVerbose(True)
# Run global routing (True enables congestion-aware routing, which is iterative)
grt.globalRoute(True)

# Configure and run detailed routing
drter = design.getTritonRoute()
params = drt.ParamStruct()

# Set optional output files
params.outputMazeFile = ""
params.outputDrcFile = ""
params.outputCmapFile = ""
params.outputGuideCoverageFile = ""
params.dbProcessNode = "" # Specify technology node if relevant

# Routing control parameters
params.enableViaGen = True # Enable automatic via generation
params.drouteEndIter = 30 # Set the number of detailed routing iterations as requested
params.viaInPinBottomLayer = "" # Optional: Restrict via-in-pin to a specific bottom layer name
params.viaInPinTopLayer = "" # Optional: Restrict via-in-pin to a specific top layer name
params.orSeed = -1 # Seed for OmniRoute (detailed router) - -1 for random
params.orK = 0 # K parameter for OmniRoute - 0 for default

# Set the minimum and maximum routing layers for detailed routing by name
params.bottomRoutingLayer = "metal1"
params.topRoutingLayer = "metal7"

params.verbose = 1 # Set verbosity level (1 is moderate)
params.cleanPatches = True # Clean up routing patches
params.doPa = True # Perform post-route antenna fixing
params.singleStepDR = False # Do not run detailed routing step-by-step
params.minAccessPoints = 1 # Minimum required access points for pins
params.saveGuideUpdates = False # Do not save guide updates

# Apply the configured parameters to the detailed router
drter.setParams(params)
# Run the detailed routing process
drter.main()

# Perform static IR drop analysis
psm_obj = design.getPDNSim()
# Create a Timing object, needed for accessing corners for analysis
timing = Timing(design)

# Find the VDD power net for analysis
vdd_net_for_ir = block.findNet("VDD")
if vdd_net_for_ir is None:
    print("Error: VDD net not found for IR drop analysis. Skipping analysis.")
else:
    # Analyze the VDD power grid IR drop.
    # IR drop analysis is performed on a power/ground net, considering all connected shapes across layers.
    # Analyzing specifically on M1 is not a standard IR drop analysis mode.
    # The analysis will calculate voltage drop across the VDD net, which includes shapes on M1 (followpins).
    # Assuming a timing corner exists for analysis (e.g., typical corner 0)
    analysis_corner = timing.getCorners()[0] if timing.getCorners() else None

    if analysis_corner:
        print(f"Running IR drop analysis on net '{vdd_net_for_ir.getName()}'...")
        # Use GeneratedSourceType_FULL to include current sources from standard cells
        source_types_for_ir = [psm.GeneratedSourceType_FULL]
        psm_obj.analyzePowerGrid(net = vdd_net_for_ir, # The power net to analyze
                                 enable_em = False, # Disable Electromagnetic analysis
                                 corner = analysis_corner, # Timing corner for analysis
                                 use_prev_solution = False, # Do not use previous solution
                                 em_file = "", # No EM file output
                                 error_file = "ir_drop_errors.log", # Output log file for errors
                                 voltage_source_file = "", # No input voltage source file
                                 voltage_file = "ir_drop_voltage.rpt", # Output file for voltage report
                                 source_type = source_types_for_ir[0]) # Type of current sources to consider
        print("IR drop analysis complete. Results written to ir_drop_voltage.rpt and ir_drop_errors.log.")
    else:
        print("Warning: No timing corner found for IR drop analysis. Skipping analysis.")

# Write the final DEF file containing the physical layout
design.writeDef("final.def")

# Optionally, write the updated Verilog netlist after CTS and filler insertion
# design.evalTclString("write_verilog final_post_layout.v")

print("Physical design flow script finished.")