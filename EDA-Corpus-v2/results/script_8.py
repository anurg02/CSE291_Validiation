import odb
import pdn
import drt
import openroad as ord

# Set the clock period and create the clock signal
clock_period_ns = 20
clock_period_ps = clock_period_ns * 1000
port_name = "clk"
clock_name = "core_clock"
# Create clock signal on the specified port
design.evalTclString(f"create_clock -period {clock_period_ps} [get_ports {port_name}] -name {clock_name}")
# Propagate the clock signal
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Initialize floorplan with target utilization and core-to-die spacing
floorplan = design.getFloorplan()
# Set target core utilization (50%)
target_utilization = 0.5
# Set core-to-die spacing (5 microns)
core_to_die_spacing_um = 5.0
core_to_die_spacing_dbu = design.micronToDBU(core_to_die_spacing_um)
# Find a default site in the technology library
site = floorplan.findSite("FreePDK45_38x28_10R_NP_162NW_34O") # Replace with actual site name from your library
if site is None:
    print("Error: Site not found. Please specify a valid site name.")
    exit()
# Initialize floorplan using target utilization and spacing
design.init_floorplan(core_util = target_utilization, 
                      core_to_die_margin = core_to_die_spacing_dbu,
                      site_name = site.getName())

# Create placement tracks based on the floorplan and site
floorplan.makeTracks()

# Configure and run I/O pin placement
io_placer = design.getIOPlacer()
io_params = io_placer.getParameters()
# Set random seed for reproducibility
io_params.setRandSeed(42)
io_params.setMinDistanceInTracks(False)
# Set minimum distance between pins (5 microns)
io_params.setMinDistance(design.micronToDBU(5.0))
io_params.setCornerAvoidance(design.micronToDBU(0)) # Avoid corners, set margin to 0
# Get metal layers for pin placement
metal8 = design.getTech().getDB().getTech().findLayer("metal8")
metal9 = design.getTech().getDB().getTech().findLayer("metal9")
# Add horizontal layer for placement (metal8)
if metal8:
    io_placer.addHorLayer(metal8)
else:
     print("Warning: Metal8 not found for IO placement.")
# Add vertical layer for placement (metal9)
if metal9:
    io_placer.addVerLayer(metal9)
else:
    print("Warning: Metal9 not found for IO placement.")
# Run I/O placement using annealing method in random mode
io_placer_random_mode = True
io_placer.runAnnealing(io_placer_random_mode)

# Place macro blocks if present
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
if len(macros) > 0:
    macro_placer = design.getMacroPlacer()
    block = design.getBlock()
    core = block.getCoreArea()
    # Set macro halo (5 microns)
    macro_halo_um = 5.0
    macro_halo_dbu = design.micronToDBU(macro_halo_um)
    macro_placer.place(
        # Use default placer parameters unless specified
        num_threads = 64, 
        halo_width = macro_halo_um,
        halo_height = macro_halo_um,
        fence_lx = block.dbuToMicrons(core.xMin()), # Constrain macros within the core area
        fence_ly = block.dbuToMicrons(core.yMin()),
        fence_ux = block.dbuToMicrons(core.xMax()),
        fence_uy = block.dbuToMicrons(core.yMax()),
        # Note: Minimum distance between macros (5um) is an outcome of placement optimization,
        # there's no direct parameter for this in the current API.
        # You can influence it with weights (e.g., area_weight) but cannot guarantee it.
    )

# Configure and run global placement for standard cells
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Disable timing driven mode for this example
gpl.setRoutabilityDrivenMode(True)
gpl.setUniformTargetDensityMode(True)
# Use default iterations for global placement (Example 1 used 10 initial iterations, but the prompt
# did not specify iterations for the current request's global placement step, only for routing).
gpl.doInitialPlace(threads = 4)
gpl.doNesterovPlace(threads = 4)
gpl.reset()

# Run initial detailed placement
opendp = design.getOpendp()
# Set maximum displacement (1 micron x, 3 microns y)
max_disp_x_um = 1.0
max_disp_y_um = 3.0
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)
# Remove filler cells if any exist before detailed placement
opendp.removeFillers()
# Perform detailed placement
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

# Configure and run clock tree synthesis
cts = design.getTritonCts()
cts_params = cts.getParms()
# Set clock buffer list (BUF_X2)
cts.setBufferList("BUF_X2")
# Set root and sink buffers (BUF_X2)
cts.setRootBuffer("BUF_X2")
cts.setSinkBuffer("BUF_X2")
# Set clock net by name
cts.setClockNets(clock_name)
# Set RC values for clock and signal nets (0.03574 resistance, 0.07516 capacitance)
design.evalTclString("set_wire_rc -clock -resistance 0.03574 -capacitance 0.07516")
design.evalTclString("set_wire_rc -signal -resistance 0.03574 -capacitance 0.07516")
# Run CTS
cts.runTritonCts()

# Run final detailed placement after CTS
# The max displacement parameters are in site units relative to site origin for this API
site = design.getBlock().getRows()[0].getSite()
max_disp_x_sites = int(design.micronToDBU(max_disp_x_um) / site.getWidth())
max_disp_y_sites = int(design.micronToDBU(max_disp_y_um) / site.getHeight())
# Remove filler cells again before final detailed placement
opendp.removeFillers()
# Perform final detailed placement
opendp.detailedPlacement(max_disp_x_sites, max_disp_y_sites, "", False)


# Configure power delivery network
pdngen = design.getPdnGen()

# Ensure power/ground nets are marked as special
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")

if VDD_net:
    VDD_net.setSigType("POWER")
    VDD_net.setSpecial()
else:
    print("Warning: VDD net not found.")
if VSS_net:
    VSS_net.setSigType("GROUND")
    VSS_net.setSpecial()
else:
     print("Warning: VSS net not found.")

# Set core power domain
pdngen.setCoreDomain(power = VDD_net,
    switched_power = None, # No switched power
    ground = VSS_net,
    secondary = []) # No secondary power nets

# Set via cut pitch (0 microns as requested, implies single cuts or default pattern)
via_cut_pitch_dbu = design.micronToDBU(0.0)
pdn_cut_pitch = [via_cut_pitch_dbu for i in range(2)]

# Get metal layers for PDN construction
m1 = design.getTech().getDB().getTech().findLayer("metal1")
m4 = design.getTech().getDB().getTech().findLayer("metal4")
m5 = design.getTech().getDB().getTech().findLayer("metal5")
m6 = design.getTech().getDB().getTech().findLayer("metal6")
m7 = design.getTech().getDB().getTech().findLayer("metal7")
m8 = design.getTech().getDB().getTech().findLayer("metal8")

# Create the main core grid structure for standard cells
domains = [pdngen.findDomain("Core")]
if domains:
    # Create the main core grid
    pdngen.makeCoreGrid(domain = domains[0],
    name = "core_grid",
    starts_with = pdn.GROUND, # Start with ground net
    pin_layers = [], # Not connecting to specific pin layers this way
    generate_obstructions = [],
    powercell = None,
    powercontrol = None,
    powercontrolnetwork = "STAR")

    core_grid = pdngen.findGrid("core_grid")
    if core_grid:
        # Add power straps to the core grid
        # Standard cell power rails (followpin) on metal1
        if m1:
            pdngen.makeFollowpin(grid = core_grid,
                layer = m1,
                width = design.micronToDBU(0.07), # 0.07um width for M1 followpin
                extend = pdn.CORE)
        else:
            print("Warning: Metal1 not found for PDN.")

        # Straps on metal4
        if m4:
            pdngen.makeStrap(grid = core_grid,
                layer = m4,
                width = design.micronToDBU(1.2), # 1.2um width
                spacing = design.micronToDBU(1.2), # 1.2um spacing
                pitch = design.micronToDBU(6.0), # 6um pitch
                offset = design.micronToDBU(0.0), # 0 offset
                number_of_straps = 0, # Auto-calculate
                snap = False, # Don't snap to grid
                starts_with = pdn.GRID, # Align with grid start
                extend = pdn.CORE, # Extend within core
                nets = []) # All nets assigned to grid domain
        else:
            print("Warning: Metal4 not found for PDN.")

        # Straps on metal7
        if m7:
            pdngen.makeStrap(grid = core_grid,
                layer = m7,
                width = design.micronToDBU(1.4), # 1.4um width
                spacing = design.micronToDBU(1.4), # 1.4um spacing
                pitch = design.micronToDBU(10.8), # 10.8um pitch
                offset = design.micronToDBU(0.0), # 0 offset
                number_of_straps = 0,
                snap = False,
                starts_with = pdn.GRID,
                extend = pdn.CORE,
                nets = [])
        else:
            print("Warning: Metal7 not found for PDN.")

        # Straps on metal8
        if m8:
            pdngen.makeStrap(grid = core_grid,
                layer = m8,
                width = design.micronToDBU(1.4), # 1.4um width
                spacing = design.micronToDBU(1.4), # 1.4um spacing
                pitch = design.micronToDBU(10.8), # 10.8um pitch
                offset = design.micronToDBU(0.0), # 0 offset
                number_of_straps = 0,
                snap = False,
                starts_with = pdn.GRID,
                extend = pdn.CORE,
                nets = [])
        else:
            print("Warning: Metal8 not found for PDN.")

        # Create power rings around the core using M7 and M8
        if m7 and m8:
            pdngen.makeRing(grid = core_grid,
                layer0 = m7, # Horizontal ring layer
                width0 = design.micronToDBU(2.0), # 2um width
                spacing0 = design.micronToDBU(2.0), # 2um spacing
                layer1 = m8, # Vertical ring layer
                width1 = design.micronToDBU(2.0), # 2um width
                spacing1 = design.micronToDBU(2.0), # 2um spacing
                starts_with = pdn.GRID,
                offset = [design.micronToDBU(0.0), design.micronToDBU(0.0), design.micronToDBU(0.0), design.micronToDBU(0.0)], # 0 offset (left, bottom, right, top)
                pad_offset = [design.micronToDBU(0.0), design.micronToDBU(0.0), design.micronToDBU(0.0), design.micronToDBU(0.0)],
                extend = pdn.CORE, # Extend to core boundary
                pad_pin_layers = [],
                nets = [])
        else:
            print("Warning: Metal7 and/or Metal8 not found for core rings.")

        # Create via connections within the core grid
        # Connect metal1 to metal4
        if m1 and m4:
            pdngen.makeConnect(grid = core_grid,
                layer0 = m1,
                layer1 = m4,
                cut_pitch_x = pdn_cut_pitch[0], # 0 pitch
                cut_pitch_y = pdn_cut_pitch[1], # 0 pitch
                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
        else:
            print("Warning: Metal1 and/or Metal4 not found for core via connections.")

        # Connect metal4 to metal7
        if m4 and m7:
            pdngen.makeConnect(grid = core_grid,
                layer0 = m4,
                layer1 = m7,
                cut_pitch_x = pdn_cut_pitch[0], # 0 pitch
                cut_pitch_y = pdn_cut_pitch[1], # 0 pitch
                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
        else:
             print("Warning: Metal4 and/or Metal7 not found for core via connections.")

        # Connect metal7 to metal8
        if m7 and m8:
             pdngen.makeConnect(grid = core_grid,
                layer0 = m7,
                layer1 = m8,
                cut_pitch_x = pdn_cut_pitch[0], # 0 pitch
                cut_pitch_y = pdn_cut_pitch[1], # 0 pitch
                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
        else:
            print("Warning: Metal7 and/or Metal8 not found for core via connections.")

# Create power grid for macro blocks if they exist
if len(macros) > 0:
    macro_halo_dbu_list = [macro_halo_dbu, macro_halo_dbu, macro_halo_dbu, macro_halo_dbu] # left, bottom, right, top halo
    for i, macro_inst in enumerate(macros):
        # Create separate power grid for each macro instance
        if domains:
            pdngen.makeInstanceGrid(domain = domains[0],
                name = f"macro_grid_{i}",
                starts_with = pdn.GROUND,
                inst = macro_inst,
                halo = macro_halo_dbu_list, # 5um halo around macro
                pg_pins_to_boundary = True,  # Connect power/ground pins to boundary of the instance grid
                default_grid = False,
                generate_obstructions = [],
                is_bump = False)

            macro_grid = pdngen.findGrid(f"macro_grid_{i}")
            if macro_grid:
                 # Add power straps to the macro grid on metal5
                 if m5:
                    pdngen.makeStrap(grid = macro_grid,
                        layer = m5,
                        width = design.micronToDBU(1.2), # 1.2um width
                        spacing = design.micronToDBU(1.2), # 1.2um spacing
                        pitch = design.micronToDBU(6.0), # 6um pitch
                        offset = design.micronToDBU(0.0), # 0 offset
                        number_of_straps = 0,
                        snap = True, # Snap to grid
                        starts_with = pdn.GRID,
                        extend = pdn.CORE, # Extend within macro instance boundary? (CORE might apply to instance bounds in this context)
                        nets = [])
                 else:
                     print(f"Warning: Metal5 not found for macro grid {i}.")

                 # Add power straps to the macro grid on metal6
                 if m6:
                    pdngen.makeStrap(grid = macro_grid,
                        layer = m6,
                        width = design.micronToDBU(1.2), # 1.2um width
                        spacing = design.micronToDBU(1.2), # 1.2um spacing
                        pitch = design.micronToDBU(6.0), # 6um pitch
                        offset = design.micronToDBU(0.0), # 0 offset
                        number_of_straps = 0,
                        snap = True,
                        starts_with = pdn.GRID,
                        extend = pdn.CORE,
                        nets = [])
                 else:
                     print(f"Warning: Metal6 not found for macro grid {i}.")

                 # Note: Creating explicit rings around each macro instance using makeRing
                 # is not straightforward with the current API design. Assuming strap grid is sufficient.

                 # Create via connections for macro grids, connecting to main grid layers
                 # Connect metal4 (from core grid) to metal5 (macro grid)
                 if m4 and m5:
                    pdngen.makeConnect(grid = macro_grid,
                        layer0 = m4,
                        layer1 = m5,
                        cut_pitch_x = pdn_cut_pitch[0], # 0 pitch
                        cut_pitch_y = pdn_cut_pitch[1], # 0 pitch
                        vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
                 else:
                     print(f"Warning: Metal4 and/or Metal5 not found for macro via connections {i}.")

                 # Connect metal5 to metal6 (within macro grid)
                 if m5 and m6:
                    pdngen.makeConnect(grid = macro_grid,
                        layer0 = m5,
                        layer1 = m6,
                        cut_pitch_x = pdn_cut_pitch[0], # 0 pitch
                        cut_pitch_y = pdn_cut_pitch[1], # 0 pitch
                        vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
                 else:
                    print(f"Warning: Metal5 and/or Metal6 not found for macro via connections {i}.")

                 # Connect metal6 (macro grid) to metal7 (core grid)
                 if m6 and m7:
                    pdngen.makeConnect(grid = macro_grid,
                        layer0 = m6,
                        layer1 = m7,
                        cut_pitch_x = pdn_cut_pitch[0], # 0 pitch
                        cut_pitch_y = pdn_cut_pitch[1], # 0 pitch
                        vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
                 else:
                    print(f"Warning: Metal6 and/or Metal7 not found for macro via connections {i}.")

# Verify and build the PDN
pdngen.checkSetup() # Verify configuration
pdngen.buildGrids(False) # Build the power grid structure
pdngen.writeToDb(True) # Write power grid to the design database
pdngen.resetShapes() # Clear temporary shapes

# Insert filler cells
db = ord.get_db()
filler_masters = list()
# Define filler cell naming convention (adjust if needed for your library)
filler_cells_prefix = "FILLCELL_"
for lib in db.getLibs():
    for master in lib.getMasters():
        # Check if master is a filler cell (CORE_SPACER type)
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

if len(filler_masters) == 0:
    print("Warning: No filler cells found in library!")
else:
    # Perform filler cell placement to fill gaps
    opendp.fillerPlacement(filler_masters = filler_masters,
                                     prefix = filler_cells_prefix,
                                     verbose = False)


# Configure and run global routing
grt = design.getGlobalRouter()
# Get routing layer levels
if m1 and m7:
    signal_low_layer = m1.getRoutingLevel()
    signal_high_layer = m7.getRoutingLevel()
    clk_low_layer = m1.getRoutingLevel() # Clock routing uses the same layer range
    clk_high_layer = m7.getRoutingLevel()

    # Set minimum and maximum routing layers for signal and clock nets (M1 to M7)
    grt.setMinRoutingLayer(signal_low_layer)
    grt.setMaxRoutingLayer(signal_high_layer)
    grt.setMinLayerForClock(clk_low_layer)
    grt.setMaxLayerForClock(clk_high_layer)
    grt.setAdjustment(0.5) # Default congestion adjustment
    grt.setVerbose(True)
    # Run global routing (The prompt mentioned 10 iterations, but the API doesn't support this directly.
    # Running standard global route.)
    grt.globalRoute(True) # True enables congestion-driven mode
else:
    print("Warning: Metal1 and/or Metal7 not found. Skipping global routing.")


# Configure and run detailed routing
drter = design.getTritonRoute()
dr_params = drt.ParamStruct()
# Configure detailed routing parameters
dr_params.outputMazeFile = "" # No debug file
dr_params.outputDrcFile = "" # No DRC file output here (can add if needed)
dr_params.outputCmapFile = ""
dr_params.outputGuideCoverageFile = ""
dr_params.dbProcessNode = ""
dr_params.enableViaGen = True # Enable via generation
dr_params.drouteEndIter = 1 # Number of detailed routing iterations
dr_params.viaInPinBottomLayer = "" # Default via in pin layers
dr_params.viaInPinTopLayer = ""
dr_params.orSeed = -1 # Random seed
dr_params.orK = 0
# Set bottom and top routing layers for detailed routing (M1 to M7)
if m1 and m7:
    dr_params.bottomRoutingLayer = m1.getName()
    dr_params.topRoutingLayer = m7.getName()
else:
    print("Warning: Metal1 and/or Metal7 not found. Detailed routing may fail or use default layers.")
dr_params.verbose = 1
dr_params.cleanPatches = True
dr_params.doPa = True # Perform post-route antenna fixing
dr_params.singleStepDR = False
dr_params.minAccessPoints = 1
dr_params.saveGuideUpdates = False
# Set the parameters for the detailed router
drter.setParams(dr_params)
# Run detailed routing
drter.main()

# Save the final DEF file
design.writeDef("final.def")

# Saving Verilog netlist after routing doesn't capture physical routing.
# Use write_def for physical layout.
# design.evalTclString("write_verilog final.v") # Optional: Write post-CTS netlist if needed