import odb
import pdn
import drt
import openroad as ord

# --- Clock Definition ---
# Create a clock signal on port "clk" with a period of 20 ns (20000 ps)
clock_period_ps = 20000
clock_port_name = "clk"
clock_name = "core_clock"
print(f"Creating clock '{clock_name}' on port '{clock_port_name}' with period {clock_period_ps} ps")
design.evalTclString(f"create_clock -period {clock_period_ps} [get_ports {clock_port_name}] -name {clock_name}")

# Propagate the clock signal
print(f"Propagating clock '{clock_name}'")
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Set unit resistance and capacitance for clock and signal nets
print("Setting wire RC values for clock and signal nets")
design.evalTclString("set_wire_rc -clock -resistance 0.03574 -capacitance 0.07516")
design.evalTclString("set_wire_rc -signal -resistance 0.03574 -capacitance 0.07516")

# --- Floorplan ---
print("Performing floorplan")
floorplan = design.getFloorplan()

# Find the first available core site
site = None
for lib in design.getTech().getDB().getLibs():
    for site_entry in lib.getSites():
        if site_entry.getType() == "CORE":
            site = site_entry
            break
    if site:
        break

if not site:
    print("Error: No CORE site found in the library.")
    exit()

# Set die area from (0,0) to (40,60) um
die_lx, die_ly, die_ux, die_uy = 0, 0, 40, 60
die_area = odb.Rect(design.micronToDBU(die_lx), design.micronToDBU(die_ly),
                    design.micronToDBU(die_ux), design.micronToDBU(die_uy))

# Set core area from (10,10) to (30,50) um
core_lx, core_ly, core_ux, core_uy = 10, 10, 30, 50
core_area = odb.Rect(design.micronToDBU(core_lx), design.micronToDBU(core_ly),
                     design.micronToDBU(core_ux), design.micronToDBU(core_uy))

# Initialize floorplan with the defined areas and site
floorplan.initFloorplan(die_area, core_area, site)
# Create placement tracks
floorplan.makeTracks()

# Dump DEF after floorplan
print("Writing DEF after floorplan")
design.writeDef("floorplan.def")

# --- Placement ---
print("Performing placement")

# Configure and run Macro Placement if macros exist
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
if len(macros) > 0:
    print(f"Found {len(macros)} macros. Performing macro placement.")
    mpl = design.getMacroPlacer()
    block = design.getBlock()

    # Macro fence region: (15,10) um to (30,40) um
    fence_lx_um, fence_ly_um, fence_ux_um, fence_uy_um = 15, 10, 30, 40

    # Minimum distance between macros: 5 um
    macro_spacing_um = 5.0

    # Halo region around each macro: 5 um
    macro_halo_um = 5.0

    mpl.place(
        # Use num_threads = 0 to let the tool decide
        num_threads = 0,
        # No constraints on max/min num instances/macros
        max_num_macro = 0,
        min_num_macro = 0,
        max_num_inst = 0,
        min_num_inst = 0,
        # Tolerance for placement, usually 0.1
        tolerance = 0.1,
        # Coarsening levels
        max_num_level = 2,
        coarsening_ratio = 10.0,
        # Net thresholds
        large_net_threshold = 50,
        signature_net_threshold = 50,
        # Halo settings
        halo_width = macro_halo_um,
        halo_height = macro_halo_um,
        # Fence region settings (in microns for the MacroPlacer API)
        fence_lx = fence_lx_um,
        fence_ly = fence_ly_um,
        fence_ux = fence_ux_um,
        fence_uy = fence_uy_um,
        # Placement weights
        area_weight = 0.1,
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        # Pin access threshold
        pin_access_th = 0.0,
        # Utilization/dead space targets
        target_util = 0.25, # Default utilization target
        target_dead_space = 0.05, # Default dead space target
        # Aspect ratio constraint
        min_ar = 0.33, # Default minimum aspect ratio
        # Snap layer for pins, usually M4 or M5
        snap_layer = 4,
        # Bus planning flag
        bus_planning_flag = False,
        # Report directory
        report_directory = "",
        # Minimum distance between macros
        macro_space = macro_spacing_um
    )
else:
    print("No macros found. Skipping macro placement.")

# Configure and run Global Placement
print("Performing global placement")
gpl = design.getReplace()
# Basic global placement settings
gpl.setTimingDrivenMode(False)
gpl.setRoutabilityDrivenMode(True)
gpl.setUniformTargetDensityMode(True)
# Number of iterations was mentioned in the prompt (maybe for GPL, not GR?) - set GPL iterations
# The user prompt said "global router as 10 times", which is unusual for GR iterations.
# Assuming they might have meant Global Placement iterations as seen in the example.
# Setting InitialPlaceMaxIter based on the example.
gpl.setInitialPlaceMaxIter(10) # Using 10 based on example, though prompt mentioned 10 for GR.
gpl.setInitDensityPenalityFactor(0.05) # Default
# Run initial placement
gpl.doInitialPlace(threads = 0) # Use 0 threads for default
# Run Nesterov placement
gpl.doNesterovPlace(threads = 0) # Use 0 threads for default
gpl.reset() # Reset the placer state

# Run initial Detailed Placement
print("Performing initial detailed placement")
opendp = design.getOpendp()
# Allow 0.5 um displacement in X and Y
max_disp_x_um = 0.5
max_disp_y_um = 0.5
# Detailed placement displacement is in sites, convert um to sites
site_width = site.getWidth()
site_height = site.getHeight()
max_disp_x_sites = int(design.micronToDBU(max_disp_x_um) / site_width)
max_disp_y_sites = int(design.micronToDBU(max_disp_y_um) / site_height)

# Remove filler cells before detailed placement if they were previously inserted
opendp.removeFillers()
# Perform detailed placement
opendp.detailedPlacement(max_disp_x_sites, max_disp_y_sites, "", False)

# Dump DEF after placement
print("Writing DEF after placement")
design.writeDef("placement.def")

# --- Clock Tree Synthesis (CTS) ---
print("Performing clock tree synthesis")
cts = design.getTritonCts()

# Set available clock buffers
buffer_cell_name = "BUF_X2"
cts.setBufferList(buffer_cell_name)
cts.setRootBuffer(buffer_cell_name)
cts.setSinkBuffer(buffer_cell_name)

# Set wire segment unit for CTS (e.g., 20 DBU units)
parms = cts.getParms()
# Assuming a default DBU value or using 20 as in example
# A reasonable value is often based on site dimensions or tracks
# Let's use 20 DBU for now based on example
parms.setWireSegmentUnit(20)

# Run CTS
cts.runTritonCts()

# Run final detailed placement after CTS to clean up cell positions
print("Performing final detailed placement after CTS")
# Displacement is in sites
opendp.detailedPlacement(max_disp_x_sites, max_disp_y_sites, "", False)

# Insert filler cells to fill empty spaces
print("Inserting filler cells")
db = ord.get_db()
filler_masters = list()
# Identify filler cells (assuming CORE_SPACER type)
filler_cells_prefix = "FILLCELL_" # Common prefix, adjust if needed
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)
if len(filler_masters) == 0:
    print("Warning: No CORE_SPACER filler cells found in library!")
else:
    opendp.fillerPlacement(filler_masters = filler_masters,
                           prefix = filler_cells_prefix,
                           verbose = False)

# Dump DEF after CTS and filler insertion
print("Writing DEF after CTS and filler insertion")
design.writeDef("cts.def")

# --- Power Delivery Network (PDN) ---
print("Configuring and building power delivery network")
pdngen = design.getPdnGen()

# Set up global power/ground connections (assuming VDD and VSS nets exist or will be created)
VDD_net_name = "VDD"
VSS_net_name = "VSS"

# Find or create VDD/VSS nets
VDD_net = design.getBlock().findNet(VDD_net_name)
VSS_net = design.getBlock().findNet(VSS_net_name)

if VDD_net is None:
    VDD_net = odb.dbNet_create(design.getBlock(), VDD_net_name)
if VSS_net is None:
    VSS_net = odb.dbNet_create(design.getBlock(), VSS_net_name)

# Mark as special nets
VDD_net.setSigType("POWER")
VSS_net.setSigType("GROUND")

# Connect power pins to global nets
# Map VDD pins to power net for all instances
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "VDD.*", net = VDD_net, do_connect = True)
# Map VSS pins to ground net for all instances
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "VSS.*", net = VSS_net, do_connect = True)
# Apply the global connections
design.getBlock().globalConnect()

# Set core power domain
pdngen.setCoreDomain(power = VDD_net, switched_power = None, ground = VSS_net, secondary = [])

# Get core domain
core_domain = pdngen.findDomain("Core")
if core_domain is None:
    print("Error: Core power domain not found.")
    exit()

# Get metal layers
m1 = design.getTech().getDB().getTech().findLayer("metal1")
m4 = design.getTech().getDB().getTech().findLayer("metal4")
m5 = design.getTech().getDB().getTech().findLayer("metal5")
m6 = design.getTech().getDB().getTech().findLayer("metal6")
m7 = design.getTech().getDB().getTech().findLayer("metal7")
m8 = design.getTech().getDB().getTech().findLayer("metal8")

if not all([m1, m4, m5, m6, m7, m8]):
    print("Error: Could not find all required metal layers (metal1, metal4, metal5, metal6, metal7, metal8).")
    exit()

# Create the main core grid structure
core_grid_name = "core_grid"
print(f"Creating core grid '{core_grid_name}'")
pdngen.makeCoreGrid(domain = core_domain,
                    name = core_grid_name,
                    starts_with = pdn.GROUND, # Start with ground net
                    pin_layers = [],
                    generate_obstructions = [],
                    powercell = None,
                    powercontrol = None,
                    powercontrolnetwork = "STAR")

core_grid = pdngen.findGrid(core_grid_name)
if core_grid is None:
    print(f"Error: Core grid '{core_grid_name}' not found after creation.")
    exit()

# Add power straps to the core grid
# M1: Followpin for standard cells
print("Adding M1 followpin straps to core grid")
pdngen.makeFollowpin(grid = core_grid,
                     layer = m1,
                     width = design.micronToDBU(0.07),
                     extend = pdn.CORE)

# M4: Strap for standard cells
print("Adding M4 straps to core grid")
pdngen.makeStrap(grid = core_grid,
                 layer = m4,
                 width = design.micronToDBU(1.2),
                 spacing = design.micronToDBU(1.2),
                 pitch = design.micronToDBU(6),
                 offset = design.micronToDBU(0),
                 number_of_straps = 0, # Auto calculate
                 snap = False,
                 starts_with = pdn.GRID,
                 extend = pdn.CORE,
                 nets = [])

# M7: Strap for standard cells/grid connection
print("Adding M7 straps to core grid")
pdngen.makeStrap(grid = core_grid,
                 layer = m7,
                 width = design.micronToDBU(1.4),
                 spacing = design.micronToDBU(1.4),
                 pitch = design.micronToDBU(10.8),
                 offset = design.micronToDBU(0),
                 number_of_straps = 0,
                 snap = False,
                 starts_with = pdn.GRID,
                 extend = pdn.CORE,
                 nets = [])

# M8: Strap for standard cells/grid connection
print("Adding M8 straps to core grid")
pdngen.makeStrap(grid = core_grid,
                 layer = m8,
                 width = design.micronToDBU(1.4),
                 spacing = design.micronToDBU(1.4),
                 pitch = design.micronToDBU(10.8),
                 offset = design.micronToDBU(0),
                 number_of_straps = 0,
                 snap = False,
                 starts_with = pdn.GRID,
                 extend = pdn.CORE,
                 nets = [])

# Add power rings around the core
print("Adding M7/M8 power rings around core")
pdngen.makeRing(grid = core_grid,
                layer0 = m7,
                width0 = design.micronToDBU(2.0),
                spacing0 = design.micronToDBU(2.0),
                layer1 = m8,
                width1 = design.micronToDBU(2.0),
                spacing1 = design.micronToDBU(2.0),
                starts_with = pdn.GROUND, # Consistent with grid start
                offset = [design.micronToDBU(0)]*4,
                pad_offset = [design.micronToDBU(0)]*4,
                extend = pdn.CORE, # Extend to core boundary
                pad_pin_layers = [],
                nets = [])

# Create power grids and rings for macro instances if they exist
if len(macros) > 0:
    print(f"Creating PDN for {len(macros)} macros")
    # Halo around macros for instance grid/ring placement
    instance_halo = [design.micronToDBU(macro_halo_um) for _ in range(4)] # Use macro halo

    for i, macro_inst in enumerate(macros):
        macro_grid_name = f"macro_grid_{i}"
        print(f"Creating PDN grid/ring for macro instance '{macro_inst.getName()}' ({macro_grid_name})")

        # Create instance grid structure for the macro
        pdngen.makeInstanceGrid(domain = core_domain, # Assuming macros are in the core domain
                                name = macro_grid_name,
                                starts_with = pdn.GROUND,
                                inst = macro_inst,
                                halo = instance_halo,
                                pg_pins_to_boundary = True, # Connect macro PG pins to grid/ring
                                default_grid = False,
                                generate_obstructions = [],
                                is_bump = False)

        macro_grid = pdngen.findGrid(macro_grid_name)
        if macro_grid is None:
            print(f"Warning: Macro grid '{macro_grid_name}' not found after creation.")
            continue # Skip adding straps/rings/connects for this macro

        # Add power straps within the macro instance grid
        # M5: Strap for macro connections
        print(f"Adding M5 straps to macro grid '{macro_grid_name}'")
        pdngen.makeStrap(grid = macro_grid,
                         layer = m5,
                         width = design.micronToDBU(1.2),
                         spacing = design.micronToDBU(1.2),
                         pitch = design.micronToDBU(6),
                         offset = design.micronToDBU(0),
                         number_of_straps = 0,
                         snap = True, # Snap to grid
                         starts_with = pdn.GRID,
                         extend = pdn.CORE, # Extend within the macro's instance grid area
                         nets = [])

        # M6: Strap for macro connections
        print(f"Adding M6 straps to macro grid '{macro_grid_name}'")
        pdngen.makeStrap(grid = macro_grid,
                         layer = m6,
                         width = design.micronToDBU(1.2),
                         spacing = design.micronToDBU(1.2),
                         pitch = design.micronToDBU(6),
                         offset = design.micronToDBU(0),
                         number_of_straps = 0,
                         snap = True,
                         starts_with = pdn.GRID,
                         extend = pdn.CORE,
                         nets = [])

        # Add power rings around the macro instance
        print(f"Adding M5/M6 power rings around macro instance '{macro_inst.getName()}'")
        pdngen.makeRing(grid = macro_grid,
                        layer0 = m5,
                        width0 = design.micronToDBU(1.5),
                        spacing0 = design.micronToDBU(1.5),
                        layer1 = m6,
                        width1 = design.micronToDBU(1.5),
                        spacing1 = design.micronToDBU(1.5),
                        starts_with = pdn.GROUND, # Consistent with grid start
                        offset = [design.micronToDBU(0)]*4,
                        pad_offset = [design.micronToDBU(0)]*4,
                        extend = pdn.BOUNDARY, # Extend to the boundary of the instance grid
                        pad_pin_layers = [],
                        nets = [])

        # Create via connections for macro instance PDN (M4-M5, M5-M6, M6-M7)
        # Connect M4 (from core grid) to M5 (macro grid)
        print(f"Adding M4-M5 vias for macro grid '{macro_grid_name}'")
        pdngen.makeConnect(grid = macro_grid,
                           layer0 = m4,
                           layer1 = m5,
                           cut_pitch_x = design.micronToDBU(0), # 0 pitch for dense via placement
                           cut_pitch_y = design.micronToDBU(0), # 0 pitch for dense via placement
                           vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")

        # Connect M5 to M6 (macro grid layers)
        print(f"Adding M5-M6 vias for macro grid '{macro_grid_name}'")
        pdngen.makeConnect(grid = macro_grid,
                           layer0 = m5,
                           layer1 = m6,
                           cut_pitch_x = design.micronToDBU(0),
                           cut_pitch_y = design.micronToDBU(0),
                           vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")

        # Connect M6 (macro grid) to M7 (core grid)
        print(f"Adding M6-M7 vias for macro grid '{macro_grid_name}'")
        pdngen.makeConnect(grid = macro_grid,
                           layer0 = m6,
                           layer1 = m7,
                           cut_pitch_x = design.micronToDBU(0),
                           cut_pitch_y = design.micronToDBU(0),
                           vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")


# Create via connections for core grid (M1-M4, M4-M7, M7-M8)
print("Adding via connections for core grid (M1-M4, M4-M7, M7-M8)")
# Connect M1 to M4
pdngen.makeConnect(grid = core_grid,
                   layer0 = m1,
                   layer1 = m4,
                   cut_pitch_x = design.micronToDBU(0), # 0 pitch for dense via placement
                   cut_pitch_y = design.micronToDBU(0), # 0 pitch for dense via placement
                   vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
# Connect M4 to M7
pdngen.makeConnect(grid = core_grid,
                   layer0 = m4,
                   layer1 = m7,
                   cut_pitch_x = design.micronToDBU(0),
                   cut_pitch_y = design.micronToDBU(0),
                   vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
# Connect M7 to M8
pdngen.makeConnect(grid = core_grid,
                   layer0 = m7,
                   layer1 = m8,
                   cut_pitch_x = design.micronToDBU(0),
                   cut_pitch_y = design.micronToDBU(0),
                   vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")


# Verify configuration and build the power grid
print("Building power grids")
pdngen.checkSetup()
pdngen.buildGrids(False) # Build the shapes
pdngen.writeToDb(True)   # Write to the design database
pdngen.resetShapes()     # Clean up temporary shapes

# Dump DEF after PDN
print("Writing DEF after PDN")
design.writeDef("pdn.def")

# --- Power Analysis (IR Drop and Total Power) ---
# This step requires parasitic extraction (e.g., Spef) which is usually done after routing.
# However, the request asks for IR drop on M1 nodes and power analysis before routing.
# This might be an unusual flow or imply a power analysis based on estimated parasitics/placement.
# Assuming the user wants to run power analysis with whatever parasitic information is available at this stage.
# Running IR Drop analysis on M1 nodes
print("Performing IR drop analysis on M1 nodes")
# The 'analyze_power' command typically runs both static and dynamic analysis if setup.
# Specifying '-ir_drop_layer M1' targets M1 for analysis.
design.evalTclString("analyze_power -ir_drop_layer metal1")

# Report power (switching, leakage, internal, total)
print("Reporting power analysis results")
# The 'report_power' command reports various power components.
design.evalTclString("report_power")

# --- Routing ---
print("Performing routing")

# Configure and run Global Routing
grt = design.getGlobalRouter()

# Set routing layer range from M1 to M7
min_route_layer = m1.getRoutingLevel()
max_route_layer = m7.getRoutingLevel()

grt.setMinRoutingLayer(min_route_layer)
grt.setMaxRoutingLayer(max_route_layer)
# Set clock layers to be same as signal layers
grt.setMinLayerForClock(min_route_layer)
grt.setMaxLayerForClock(max_route_layer)

# Optional: Set adjustment for congestion (e.g., 0.5 = 50% extra capacity)
grt.setAdjustment(0.5)
grt.setVerbose(True)

print(f"Running global routing from layer {m1.getName()} to {m7.getName()}")
# globalRoute(is_clock_global_routed) - False means clock is not globally routed (handled by CTS)
grt.globalRoute(False)

# Dump DEF after Global Routing
print("Writing DEF after global routing")
design.writeDef("global_routing.def")

# Configure and run Detailed Routing
drter = design.getTritonRoute()
params = drt.ParamStruct()

# Set routing layer range from M1 to M7
params.bottomRoutingLayer = m1.getName()
params.topRoutingLayer = m7.getName()

# Other common detailed routing parameters
params.verbose = 1
params.cleanPatches = True
params.doPa = True # Perform post-routing antenna fixing
params.singleStepDR = False
params.minAccessPoints = 1
params.saveGuideUpdates = False
params.enableViaGen = True
params.drouteEndIter = 1 # Number of detailed routing iterations (usually 1)

drter.setParams(params)
print(f"Running detailed routing from layer {params.bottomRoutingLayer} to {params.topRoutingLayer}")
drter.main()

# Dump DEF after Detailed Routing
print("Writing DEF after detailed routing")
design.writeDef("detailed_routing.def")

# --- Final Output ---
# Write final DEF file
print("Writing final DEF file")
design.writeDef("final.def")

# Write final Verilog netlist (post-route netlist)
print("Writing final Verilog netlist")
# OpenROAD uses write_verilog Tcl command for this
design.evalTclString("write_verilog final.v")

print("Script finished.")