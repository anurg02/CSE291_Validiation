import odb
import pdn
import drt
import openroad as ord

# Assuming design and technology are already loaded, e.g.:
# design.readCheckpoint("path/to/input.chk")
# design.readVerilog("path/to/input.v")
# design.readLef("path/to/tech.lef")
# design.readLef("path/to/libs.lef")
# design.readDb("path/to/lib.db")

# Define clock properties
clock_period_ns = 50 # in nanoseconds
clock_period_ps = clock_period_ns * 1000 # Convert to picoseconds for TCL command
clock_port_name = "clk"
clock_name = "core_clock"

# Create clock signal
# This TCL command creates a clock object associated with the port
design.evalTclString(f"create_clock -period {clock_period_ps} [get_ports {clock_port_name}] -name {clock_name}")
# Propagate the clock signal throughout the design
design.evalTclString("set_propagated_clock [all_clocks]")

# Initialize floorplan
floorplan = design.getFloorplan()

# Define die area (bottom-left 0,0 to top-right 40,60 in microns)
die_area_lx = design.micronToDBU(0)
die_area_ly = design.micronToDBU(0)
die_area_ux = design.micronToDBU(40)
die_area_uy = design.micronToDBU(60)
die_area = odb.Rect(die_area_lx, die_area_ly, die_area_ux, die_area_uy)

# Define core area (bottom-left 10,10 to top-right 30,50 in microns)
core_area_lx = design.micronToDBU(10)
core_area_ly = design.micronToDBU(10)
core_area_ux = design.micronToDBU(30)
core_area_uy = design.micronToDBU(50)
core_area = odb.Rect(core_area_lx, core_area_ly, core_area_ux, core_area_uy)

# Find a site to initialize the floorplan (e.g., "FreePDK45_38x28_10R_NP_162NW_34O" or similar from your tech LEF)
# You might need to replace "YourSiteName" with the actual site name from your LEF file
# Iterate through libraries to find a core site if the name is unknown
site = None
for lib in design.getDb().getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE":
            site = master.getSite()
            if site:
                print(f"Found CORE site: {site.getName()}")
                break
    if site:
        break

if site is None:
    print("Error: No CORE site found in libraries.")
    # Exit or handle error appropriately
    exit(1)

# Initialize the floorplan with the defined areas and site
floorplan.initFloorplan(die_area, core_area, site)
# Create placement tracks based on the technology and floorplan
floorplan.makeTracks()

# Identify macro blocks
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

# If macros exist, configure and run macro placement
if len(macros) > 0:
    print(f"Found {len(macros)} macros. Performing macro placement.")
    mpl = design.getMacroPlacer()
    block = design.getBlock()

    # Set fence region for macros (15 um, 10 um) to (30 um, 40 um)
    fence_lx_um = 15.0
    fence_ly_um = 10.0
    fence_ux_um = 30.0
    fence_uy_um = 40.0

    # Configure macro placement parameters
    mpl_params = {
        # Set fence region in microns
        "fence_lx": fence_lx_um,
        "fence_ly": fence_ly_um,
        "fence_ux": fence_ux_um,
        "fence_uy": fence_uy_um,
        # Set halo region around each macro in microns
        "halo_width": 5.0,
        "halo_height": 5.0,
        # Set minimum distance between macros in microns (approximated via tolerance/weights)
        # Note: min_num_macro_dist is mentioned in the request, but not in the example API.
        # The example uses weights and tolerances. Let's use available parameters.
        # Setting min_num_macro_dist directly isn't available in the provided examples.
        # We rely on area/overlap weights and potentially post-processing if exact distance is critical.
        # Based on example, mpl.place handles halo and fence directly.
        # Minimum distance constraint is often handled implicitly by the placer engine's cost function
        # or requires specific parameters not in the provided list.
        # We will set the halo and fence as requested.
        "num_threads": 64,
        # Add other potentially relevant parameters from the example if needed,
        # but focus on the requested ones (fence, halo, min distance).
        # Min distance between macros is difficult to enforce directly with the provided API list.
        # The halo acts as a buffer, which helps maintain separation.
        # The fence confines them.
    }

    # Run macro placement
    # Note: The provided example runs mpl.place with many parameters.
    # Let's use the most relevant ones based on the prompt (fence, halo)
    # and use a reasonable default for others if not specified.
    # Re-using parameters from Example 1's mpl.place for robustness
    core = block.getCoreArea()
    mpl.place(
        num_threads = 64,
        max_num_macro = len(macros)//8 if len(macros) > 8 else len(macros), # Heuristic from example
        min_num_macro = 0,
        max_num_inst = 0,
        min_num_inst = 0,
        tolerance = 0.1, # From example
        max_num_level = 2, # From example
        coarsening_ratio = 10.0, # From example
        large_net_threshold = 50, # From example
        signature_net_threshold = 50, # From example
        halo_width = mpl_params["halo_width"], # From request
        halo_height = mpl_params["halo_height"], # From request
        fence_lx = design.micronToDBU(mpl_params["fence_lx"]), # From request
        fence_ly = design.micronToDBU(mpl_params["fence_ly"]), # From request
        fence_ux = design.micronToDBU(mpl_params["fence_ux"]), # From request
        fence_uy = design.micronToDBU(mpl_params["fence_uy"]), # From request
        # Other weights from example if needed, but not explicitly requested
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
        snap_layer = 4, # Example uses M4
        bus_planning_flag = False,
        report_directory = ""
    )
    print("Macro placement complete.")
else:
    print("No macros found. Skipping macro placement.")


# Configure and run global placement
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Or True if timing data is loaded
gpl.setRoutabilityDrivenMode(True)
gpl.setUniformTargetDensityMode(True)
# Run global placement stages
gpl.doInitialPlace(threads = 4) # Initial placement
gpl.doNesterovPlace(threads = 4) # Nesterov-based global placement
gpl.reset() # Reset internal data structures

# Run detailed placement
site = design.getBlock().getRows()[0].getSite()
# Define maximum displacement for detailed placement in microns
max_disp_x_um = 0.5
max_disp_y_um = 0.5
# Convert microns to DBU and then to site units if needed, or directly to DBU
# The API example uses DBU directly. Let's follow that.
max_disp_x_dbu = int(design.micronToDBU(max_disp_x_um))
max_disp_y_dbu = int(design.micronToDBU(max_disp_y_um))

# Remove fillers before detailed placement if they exist
design.getOpendp().removeFillers()
# Perform detailed placement with specified maximum displacement
design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Placement (Global + Detailed) complete.")

# Configure and run clock tree synthesis (CTS)
print("Starting Clock Tree Synthesis (CTS)...")
# Set propagated clock (already done with set_propagated_clock [all_clocks] above)
# design.evalTclString("set_propagated_clock [get_clocks {core_clock}]") # Redundant if all_clocks is used

# Set RC values for clock and signal nets
rc_resistance = 0.03574
rc_capacitance = 0.07516
design.evalTclString(f"set_wire_rc -clock -resistance {rc_resistance} -capacitance {rc_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {rc_resistance} -capacitance {rc_capacitance}")

# Get the CTS module
cts = design.getTritonCts()
parms = cts.getParms()
parms.setWireSegmentUnit(20) # Example value

# Set clock buffer list and root/sink buffers
buffer_cell_name = "BUF_X2"
cts.setBufferList(buffer_cell_name)
cts.setRootBuffer(buffer_cell_name)
cts.setSinkBuffer(buffer_cell_name)

# Set the clock net for CTS
# cts.setClockNets(clock_name) # API example doesn't show setting net by name here, relies on propagated clock

# Run CTS
cts.runTritonCts()
print("Clock Tree Synthesis (CTS) complete.")

# Configure and build Power Delivery Network (PDN)
print("Building Power Delivery Network (PDN)...")
pdngen = design.getPdnGen()

# Set up global power/ground connections if not already defined in netlist
# Find existing power and ground nets or create if needed
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")

if VDD_net is None:
    VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
    VDD_net.setSigType("POWER")
    VDD_net.setSpecial()
if VSS_net is None:
    VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
    VSS_net.setSigType("GROUND")
    VSS_net.setSpecial()

# Connect standard cell power pins to global nets
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
# Add other potential VDD/VSS pin names if known (e.g., VDDCE, VSSPE from example)
design.getBlock().globalConnect()

# Set the core power domain
pdngen.setCoreDomain(power = VDD_net, switched_power = None, ground = VSS_net, secondary = [])

# Get required metal layers
tech = design.getTech().getDB().getTech()
m1 = tech.findLayer("metal1")
m4 = tech.findLayer("metal4")
m5 = tech.findLayer("metal5")
m6 = tech.findLayer("metal6")
m7 = tech.findLayer("metal7")
m8 = tech.findLayer("metal8")

# Define via cut pitch and offset (0 um as requested)
pdn_cut_pitch_x_dbu = design.micronToDBU(0)
pdn_cut_pitch_y_dbu = design.micronToDBU(0)
pdn_offset_dbu = design.micronToDBU(0)

# Create the main core grid for standard cells
domains = [pdngen.findDomain("Core")]
for domain in domains:
    pdngen.makeCoreGrid(domain = domain,
        name = "stdcell_grid",
        starts_with = pdn.GROUND, # Example starts with GROUND, request doesn't specify
        pin_layers = [],
        generate_obstructions = [],
        powercell = None,
        powercontrol = None,
        powercontrolnetwork = "STAR") # Example uses STAR

# Get the created standard cell grid
stdcell_grid = pdngen.findGrid("stdcell_grid")

# Add standard cell PDN elements
for grid in stdcell_grid:
    # M1: Followpin straps (width 0.07 um)
    if m1:
        pdngen.makeFollowpin(grid = grid, layer = m1, width = design.micronToDBU(0.07), extend = pdn.CORE)

    # M4: Straps (width 1.2 um, spacing 1.2 um, pitch 6 um)
    if m4:
        pdngen.makeStrap(grid = grid, layer = m4, width = design.micronToDBU(1.2), spacing = design.micronToDBU(1.2),
                         pitch = design.micronToDBU(6), offset = pdn_offset_dbu, number_of_straps = 0,
                         snap = False, starts_with = pdn.GRID, extend = pdn.CORE, nets = [])

    # M7: Straps (width 1.4 um, spacing 1.4 um, pitch 10.8 um)
    if m7:
         pdngen.makeStrap(grid = grid, layer = m7, width = design.micronToDBU(1.4), spacing = design.micronToDBU(1.4),
                         pitch = design.micronToDBU(10.8), offset = pdn_offset_dbu, number_of_straps = 0,
                         snap = False, starts_with = pdn.GRID, extend = pdn.CORE, nets = [])

    # M7: Rings (width 4 um, spacing 4 um) - Rings are typically placed on the boundary or around specific areas.
    # The prompt asks for rings "on M7 and M8". Let's assume this means along the core boundary.
    # The API makeRing is suitable for rings around design/macro boundary.
    # The makeCoreGrid does not automatically create rings. Need to call makeRing separately.
    # Note: makeRing takes width and spacing for *two* layers. Need to check API description carefully.
    # API 9: makeRing(grid, layer0, width0, spacing0, layer1, width1, spacing1, starts_with, offset, pad_offset, extend, pad_pin_layers, nets)
    # This API description suggests pairs of layers. The prompt asks for rings *on* M7 and *on* M8, which might imply horizontal on one, vertical on another, or independent rings.
    # A common approach is horizontal on one, vertical on another. Let's put horizontal on M7 and vertical on M8 around the core.
    # The prompt implies separate ring settings for M7 and M8. Let's interpret this as horizontal M7 and vertical M8.
    # Layer 0 (horizontal): M7, width 4um, spacing 4um
    # Layer 1 (vertical): M8, width 4um, spacing 4um
    # The makeRing API takes width/spacing for layer0 and layer1.
    # Let's try to create a ring using M7 (hor) and M8 (ver) with specified settings.
    # The 'offset' and 'pad_offset' parameters seem to control the ring position relative to the boundary. 0 um offset as requested.
    # The 'extend' parameter can extend to BOUNDARY. Let's use that.
    # 'starts_with' can be pdn.GRID, pdn.POWER, pdn.GROUND. Let's use pdn.GRID.
    # The API takes *two* layer parameters. It's designed for rings on two perpendicular layers.
    # Let's assume M7 is preferred horizontal and M8 vertical for the core ring.
    if m7 and m8:
        # Assuming M7 is horizontal preference, M8 vertical for core rings
        # The API needs layer0 and layer1. Let's map based on typical routing directions.
        # The API description for makeRing is a bit ambiguous on which layer is hor/ver.
        # Let's assume layer0 is horizontal and layer1 is vertical for a typical core ring.
        # Need to confirm layer orientations from tech LEF. Let's assume M7=Hor, M8=Ver based on common usage patterns.
        # If M7 and M8 have the same orientation, the API might be used differently or not suitable for this exact request.
        # Given the API signature, it's likely for a two-layer ring structure.
        # Let's create a ring using M7 and M8.
        # Re-reading the API: layer0, layer1 are just the two layers used. The orientation is determined by the grid/tech.
        # Let's try creating a ring using M7 and M8 with the specified width/spacing for each.
        # API: makeRing(grid, layer0, width0, spacing0, layer1, width1, spacing1, starts_with, offset, pad_offset, extend, pad_pin_layers, nets)
        # Layer0=M7, width0=4um, spacing0=4um
        # Layer1=M8, width1=4um, spacing1=4um
        # offset/pad_offset = 0 um
        # extend = pdn.BOUNDARY
        ring_offset_dbu = [pdn_offset_dbu, pdn_offset_dbu, pdn_offset_dbu, pdn_offset_dbu] # lx, ly, ux, uy offset
        pad_offset_dbu = [pdn_offset_dbu, pdn_offset_dbu] # pad offset x, y
        pdngen.makeRing(grid = grid,
                        layer0 = m7, width0 = design.micronToDBU(4), spacing0 = design.micronToDBU(4),
                        layer1 = m8, width1 = design.micronToDBU(4), spacing1 = design.micronToDBU(4),
                        starts_with = pdn.GRID, # Or pdn.POWER/pdn.GROUND depending on what the ring starts with
                        offset = ring_offset_dbu,
                        pad_offset = pad_offset_dbu,
                        extend = pdn.BOUNDARY, # Extend to boundary as common for core rings
                        pad_pin_layers = [], # No pads connecting to these rings specified
                        nets = []) # No specific nets specified for these rings (assumes VDD/VSS)


    # Via connections for standard cell grid
    # Connect M1 to M4
    if m1 and m4:
        pdngen.makeConnect(grid = grid, layer0 = m1, layer1 = m4,
                           cut_pitch_x = pdn_cut_pitch_x_dbu, cut_pitch_y = pdn_cut_pitch_y_dbu,
                           vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [],
                           split_cuts = dict(), dont_use_vias = "")
    # Connect M4 to M7
    if m4 and m7:
        pdngen.makeConnect(grid = grid, layer0 = m4, layer1 = m7,
                           cut_pitch_x = pdn_cut_pitch_x_dbu, cut_pitch_y = pdn_cut_pitch_y_dbu,
                           vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [],
                           split_cuts = dict(), dont_use_vias = "")
    # Connect M7 to M8 (for straps/rings)
    if m7 and m8:
         pdngen.makeConnect(grid = grid, layer0 = m7, layer1 = m8,
                           cut_pitch_x = pdn_cut_pitch_x_dbu, cut_pitch_y = pdn_cut_pitch_y_dbu,
                           vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [],
                           split_cuts = dict(), dont_use_vias = "")


# If macros exist, create PDN for them
if len(macros) > 0:
    print("Building PDN for macros...")
    macro_halo = [design.micronToDBU(5) for i in range(4)] # Halo matches placement halo
    m5 = tech.findLayer("metal5")
    m6 = tech.findLayer("metal6")

    for i, macro_inst in enumerate(macros):
        macro_grid_name = f"macro_grid_{i}"
        # Create instance grid for each macro
        for domain in domains:
            pdngen.makeInstanceGrid(domain = domain,
                name = macro_grid_name,
                starts_with = pdn.GROUND, # Example uses GROUND, request doesn't specify
                inst = macro_inst,
                halo = macro_halo, # Halo around the macro instance
                pg_pins_to_boundary = True, # Connect PG pins to boundary
                default_grid = False,
                generate_obstructions = [],
                is_bump = False)

        macro_grid = pdngen.findGrid(macro_grid_name)
        for grid in macro_grid:
            # M5: Straps (width 1.2 um, spacing 1.2 um, pitch 6 um)
            if m5:
                pdngen.makeStrap(grid = grid, layer = m5, width = design.micronToDBU(1.2), spacing = design.micronToDBU(1.2),
                                 pitch = design.micronToDBU(6), offset = pdn_offset_dbu, number_of_straps = 0,
                                 snap = True, starts_with = pdn.GRID, extend = pdn.CORE, nets = []) # Example uses snap=True

            # M6: Straps (width 1.2 um, spacing 1.2 um, pitch 6 um)
            if m6:
                pdngen.makeStrap(grid = grid, layer = m6, width = design.micronToDBU(1.2), spacing = design.micronToDBU(1.2),
                                 pitch = design.micronToDBU(6), offset = pdn_offset_dbu, number_of_straps = 0,
                                 snap = True, starts_with = pdn.GRID, extend = pdn.CORE, nets = []) # Example uses snap=True

            # M5: Rings (width 1.5 um, spacing 1.5 um) around macro boundary
            # M6: Rings (width 1.5 um, spacing 1.5 um) around macro boundary
            # Similar to core rings, makeRing is for a two-layer structure.
            # Let's assume M5 is horizontal and M6 is vertical preference for macro rings.
            if m5 and m6:
                 macro_ring_offset_dbu = [pdn_offset_dbu, pdn_offset_dbu, pdn_offset_dbu, pdn_offset_dbu]
                 macro_pad_offset_dbu = [pdn_offset_dbu, pdn_offset_dbu]
                 pdngen.makeRing(grid = grid,
                                 layer0 = m5, width0 = design.micronToDBU(1.5), spacing0 = design.micronToDBU(1.5),
                                 layer1 = m6, width1 = design.micronToDBU(1.5), spacing1 = design.micronToDBU(1.5),
                                 starts_with = pdn.GRID, # Or POWER/GROUND
                                 offset = macro_ring_offset_dbu,
                                 pad_offset = macro_pad_offset_dbu,
                                 extend = pdn.BOUNDARY, # Extend to macro boundary
                                 pad_pin_layers = [],
                                 nets = [])

            # Via connections for macro grid
            # Connect M4 (from core grid) to M5 (macro grid)
            if m4 and m5:
                pdngen.makeConnect(grid = grid, layer0 = m4, layer1 = m5,
                                   cut_pitch_x = pdn_cut_pitch_x_dbu, cut_pitch_y = pdn_cut_pitch_y_dbu,
                                   vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [],
                                   split_cuts = dict(), dont_use_vias = "")
            # Connect M5 to M6 (macro grid layers)
            if m5 and m6:
                pdngen.makeConnect(grid = grid, layer0 = m5, layer1 = m6,
                                   cut_pitch_x = pdn_cut_pitch_x_dbu, cut_pitch_y = pdn_cut_pitch_y_dbu,
                                   vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [],
                                   split_cuts = dict(), dont_use_vias = "")
            # Connect M6 (macro grid) to M7 (core grid)
            if m6 and m7:
                pdngen.makeConnect(grid = grid, layer0 = m6, layer1 = m7,
                                   cut_pitch_x = pdn_cut_pitch_x_dbu, cut_pitch_y = pdn_cut_pitch_y_dbu,
                                   vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [],
                                   split_cuts = dict(), dont_use_vias = "")


# Verify and build the PDN
pdngen.checkSetup() # Verify configuration
pdngen.buildGrids(False) # Build the power grid geometry
pdngen.writeToDb(True) # Write generated PDN shapes to the design database
pdngen.resetShapes() # Reset temporary shapes after writing to DB
print("Power Delivery Network (PDN) complete.")

# Insert filler cells after placement and CTS to fill empty spaces
print("Inserting filler cells...")
# Find filler cell masters in the library (assuming CORE_SPACER type and "FILLCELL_" prefix from example)
filler_masters = list()
filler_cells_prefix = "FILLCELL_"
db = ord.get_db()
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

if len(filler_masters) == 0:
    print("Warning: No CORE_SPACER type filler cells found in libraries. Skipping filler insertion.")
else:
    # Perform filler placement
    design.getOpendp().fillerPlacement(filler_masters = filler_masters,
                                     prefix = filler_cells_prefix,
                                     verbose = False)
    print("Filler cell insertion complete.")

# Configure and run global routing
print("Starting Global Routing...")
grt = design.getGlobalRouter()

# Set minimum and maximum routing layers (M1 to M7)
min_routing_layer = tech.findLayer("metal1").getRoutingLevel()
max_routing_layer = tech.findLayer("metal7").getRoutingLevel()
grt.setMinRoutingLayer(min_routing_layer)
grt.setMaxRoutingLayer(max_routing_layer)

# Set minimum and maximum clock routing layers (M1 to M7)
# Assuming the same range for clock nets as signal nets
grt.setMinLayerForClock(min_routing_layer)
grt.setMaxLayerForClock(max_routing_layer)

grt.setAdjustment(0.5) # Example value
grt.setVerbose(True)

# Run global routing
# Note: The prompt asked for 20 global router iterations.
# The provided API example 'globalRoute(True)' does not expose an iteration count.
# The number of iterations might be controlled internally or is part of the detailed router settings.
# We will proceed with the available API call. The detailed router iterations are set below.
grt.globalRoute(True) # True typically means finalize/write to DB after global route
print("Global Routing complete.")

# Configure and run detailed routing
print("Starting Detailed Routing...")
drter = design.getTritonRoute()
params = drt.ParamStruct()

# Set parameters for detailed router
params.outputMazeFile = ""
params.outputDrcFile = ""
params.outputCmapFile = ""
params.outputGuideCoverageFile = ""
params.dbProcessNode = "" # Technology process node string if needed
params.enableViaGen = True # Enable via generation
params.drouteEndIter = 20 # Set detailed routing iterations to 20 as requested (interpreted from "global router iterations")
params.viaInPinBottomLayer = "" # Optional: restrict via-in-pin layers
params.viaInPinTopLayer = ""   # Optional: restrict via-in-pin layers
params.orSeed = -1 # Random seed (-1 for default)
params.orK = 0 # Maze routing expansion cost factor
params.bottomRoutingLayer = "metal1" # Set minimum routing layer name
params.topRoutingLayer = "metal7" # Set maximum routing layer name
params.verbose = 1 # Verbosity level
params.cleanPatches = True # Clean route patches
params.doPa = True # Perform post-route antenna fixing
params.singleStepDR = False # Run detailed routing in single step (False for multi-iter)
params.minAccessPoints = 1 # Minimum number of access points per pin
params.saveGuideUpdates = False # Save guide updates during routing

# Set the parameters for the detailed router instance
drter.setParams(params)

# Run detailed routing
drter.main()
print("Detailed Routing complete.")

# IR Drop Analysis - Note: No API for IR drop analysis was provided in the knowledge base.
# This step cannot be implemented with the available information.
# print("Performing IR Drop Analysis on metal1...")
# Add code here if API becomes available, e.g., design.getIRAnalysis().run("metal1")
# print("IR Drop Analysis complete.")

# Write final DEF file
print("Writing final DEF file...")
design.writeDef("final.def")
print("Final DEF file saved as final.def")

# Writing final Verilog netlist is not explicitly requested after routing in this prompt,
# but is sometimes done. Omitted as per prompt.
# print("Writing final Verilog netlist...")
# design.evalTclString("write_verilog final.v")
# print("Final Verilog netlist saved as final.v")

print("Physical design flow complete.")