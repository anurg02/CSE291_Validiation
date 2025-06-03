import odb
import pdn
import drt
import openroad as ord
import opendp

# Define design parameters in microns
die_lx = 0.0
die_ly = 0.0
die_ux = 45.0
die_uy = 45.0
core_lx = 5.0
core_ly = 5.0
core_ux = 40.0
core_uy = 40.0
macro_fence_lx = 5.0
macro_fence_ly = 5.0
macro_fence_ux = 20.0
macro_fence_uy = 25.0
macro_halo_width = 5.0
macro_halo_height = 5.0
detailed_placement_max_disp_x = 0.5
detailed_placement_max_disp_y = 0.5
clock_period_ns = 50.0
clock_port_name = "clk"
clock_net_name = "core_clock"
wire_resistance = 0.03574
wire_capacitance = 0.07516
std_cell_m1_width = 0.07
std_cell_m4_width = 1.2
std_cell_m4_spacing = 1.2
std_cell_m4_pitch = 6.0
ring_m7_width = 4.0
ring_m7_spacing = 4.0
ring_m8_width = 4.0
ring_m8_spacing = 4.0
macro_m5_width = 1.2
macro_m5_spacing = 1.2
macro_m5_pitch = 6.0
macro_m6_width = 1.2
macro_m6_spacing = 1.2
macro_m6_pitch = 6.0
via_pitch_x = 0.0
via_pitch_y = 0.0

# Convert microns to DBU
def micron_to_dbu(microns):
    """Converts a value in microns to database units (DBU)."""
    return design.micronToDBU(microns)

# Create clock signal
# Create a clock signal on the specified port with the given period (in picoseconds)
design.evalTclString("create_clock -period %f [get_ports %s] -name %s" % (clock_period_ns * 1000, clock_port_name, clock_net_name))

# Set wire RC values for clock and signal nets
# Set unit resistance and capacitance for clock wires
design.evalTclString("set_wire_rc -clock -resistance %f -capacitance %f" % (wire_resistance, wire_capacitance))
# Set unit resistance and capacitance for signal wires
design.evalTclString("set_wire_rc -signal -resistance %f -capacitance %f" % (wire_resistance, wire_capacitance))
# Propagate the clock signal
design.evalTclString("set_propagated_clock [get_clocks {%s}]" % clock_net_name)

# Initialize floorplan
floorplan = design.getFloorplan()
# Set die area
die_area = odb.Rect(micron_to_dbu(die_lx), micron_to_dbu(die_ly),
                    micron_to_dbu(die_ux), micron_to_dbu(die_uy))
# Set core area
core_area = odb.Rect(micron_to_dbu(core_lx), micron_to_dbu(core_ly),
                     micron_to_dbu(core_ux), micron_to_dbu(core_uy))

# Find a core site from the library
site = None
for lib in design.getDb().getLibs():
    site = lib.findSite("CORE") # Assuming 'CORE' is a common site name
    if site:
        break
if not site:
    # Fallback: Find the first site that is 'CORE' type
    for lib in design.getDb().getLibs():
        for s in lib.getSites():
            if s.getType() == "CORE":
                 site = s
                 break
        if site:
            break

if not site:
    print("Error: Could not find a CORE site in the libraries.")
    # Exit or raise an error
    exit()

# Initialize floorplan with the calculated die and core areas and the found site
floorplan.initFloorplan(die_area, core_area, site)
# Make tracks on the floorplan
floorplan.makeTracks()

# Power Delivery Network setup
# Mark power and ground nets as special
for net in design.getBlock().getNets():
    if net.getSigType() == "POWER" or net.getSigType() == "GROUND":
        net.setSpecial()

# Find or create power and ground nets
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")

# Create VDD net if it doesn't exist
if VDD_net is None:
    VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
    VDD_net.setSigType("POWER")
    VDD_net.setSpecial()

# Create VSS net if it doesn't exist
if VSS_net is None:
    VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
    VSS_net.setSigType("GROUND")
    VSS_net.setSpecial()

# Global connect standard cell power pins to VDD/VSS nets
design.getBlock().addGlobalConnect(region = None,
    instPattern = ".*",
    pinPattern = "^VDD$",
    net = VDD_net,
    do_connect = True)
design.getBlock().addGlobalConnect(region = None,
    instPattern = ".*",
    pinPattern = "^VSS$",
    net = VSS_net,
    do_connect = True)
design.getBlock().globalConnect()

# Configure power domains
pdngen = design.getPdnGen()
# Set core power domain
pdngen.setCoreDomain(power = VDD_net,
    switched_power = None, # No switched power domain
    ground = VSS_net,
    secondary = []) # No secondary power nets

# Get metal layers from technology database
tech = design.getTech().getDB().getTech()
m1 = tech.findLayer("metal1")
m4 = tech.findLayer("metal4")
m5 = tech.findLayer("metal5")
m6 = tech.findLayer("metal6")
m7 = tech.findLayer("metal7")
m8 = tech.findLayer("metal8")

# Check if required layers are found
required_layers = [m1, m4, m7, m8]
required_layer_names = ["metal1", "metal4", "metal7", "metal8"]
if len([l for l in required_layers if l is not None]) != len(required_layers):
    print(f"Error: Missing one or more required metal layers: {', '.join(required_layer_names)}. Exiting.")
    exit()

# Check if macro layers are needed and found
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
if len(macros) > 0:
    required_macro_layers = [m5, m6]
    required_macro_layer_names = ["metal5", "metal6"]
    if len([l for l in required_macro_layers if l is not None]) != len(required_macro_layers):
        print(f"Error: Design has macros but missing required macro metal layers: {', '.join(required_macro_layer_names)}. Exiting.")
        exit()


# Create core power grid structure
domains = [pdngen.findDomain("Core")]
# Halo for core grid around obstructions (e.g., macros) - set to 0 for now as halo is handled during placement
core_grid_halo = [micron_to_dbu(0) for i in range(4)] # lx, ly, ux, uy

for domain in domains:
    # Create the main core grid structure
    pdngen.makeCoreGrid(domain = domain,
        name = "core_grid",
        starts_with = pdn.GROUND, # Arbitrarily start with ground
        pin_layers = [],
        generate_obstructions = [],
        powercell = None,
        powercontrol = None,
        powercontrolnetwork = "STAR") # Default connection method

core_grids = pdngen.findGrid("core_grid")
for g in core_grids:
    # Create horizontal power straps on metal1 following standard cell pins
    pdngen.makeFollowpin(grid = g,
        layer = m1,
        width = micron_to_dbu(std_cell_m1_width),
        extend = pdn.CORE)

    # Create vertical power straps on metal4 for standard cells
    pdngen.makeStrap(grid = g,
        layer = m4,
        width = micron_to_dbu(std_cell_m4_width),
        spacing = micron_to_dbu(std_cell_m4_spacing),
        pitch = micron_to_dbu(std_cell_m4_pitch),
        offset = micron_to_dbu(0),
        number_of_straps = 0, # Auto-calculate
        snap = False, # Do not snap to grid
        starts_with = pdn.GRID,
        extend = pdn.CORE,
        nets = [])

    # Create power rings on metal7 and metal8 around the core area
    # makeRing takes two layers (layer0, layer1) and parameters for each.
    # The prompt specifies rings on M7 and M8 with specific width/spacing for both.
    pdngen.makeRing(grid = g,
        layer0 = m7,
        width0 = micron_to_dbu(ring_m7_width),
        spacing0 = micron_to_dbu(ring_m7_spacing),
        layer1 = m8,
        width1 = micron_to_dbu(ring_m8_width),
        spacing1 = micron_to_dbu(ring_m8_spacing),
        starts_with = pdn.GRID, # Arbitrary start
        offset = [micron_to_dbu(0) for i in range(4)], # Offsets: top, bottom, left, right
        pad_offset = [micron_to_dbu(0) for i in range(4)], # Padding offsets
        extend = pdn.CORE, # Extend to core boundary
        pad_pin_layers = [],
        nets = [])

    # Create via connections between core grid layers
    # Connect M1 to M4
    pdngen.makeConnect(grid = g,
        layer0 = m1,
        layer1 = m4,
        cut_pitch_x = micron_to_dbu(via_pitch_x),
        cut_pitch_y = micron_to_dbu(via_pitch_y),
        vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
    # Connect M4 to M7
    pdngen.makeConnect(grid = g,
        layer0 = m4,
        layer1 = m7,
        cut_pitch_x = micron_to_dbu(via_pitch_x),
        cut_pitch_y = micron_to_dbu(via_pitch_y),
        vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
    # Connect M7 to M8 (within the ring structure)
    pdngen.makeConnect(grid = g,
        layer0 = m7,
        layer1 = m8,
        cut_pitch_x = micron_to_dbu(via_pitch_x),
        cut_pitch_y = micron_to_dbu(via_pitch_y),
        vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")


# Create power grid for macro blocks if they exist
if len(macros) > 0:
    print("Design contains macros. Generating macro power grids.")
    macro_grid_halo = [micron_to_dbu(0) for i in range(4)] # Halo around macro instance for PDN generation

    for i in range(len(macros)):
        macro_inst = macros[i]
        macro_grid_name = "macro_grid_" + str(macro_inst.getName())
        # Create a separate instance grid for each macro
        for domain in domains:
            pdngen.makeInstanceGrid(domain = domain,
                name = macro_grid_name,
                starts_with = pdn.GROUND, # Arbitrary start
                inst = macro_inst,
                halo = macro_grid_halo, # Halo around the macro instance for this grid definition
                pg_pins_to_boundary = True,
                default_grid = False,
                generate_obstructions = [],
                is_bump = False)

    for macro_inst in macros:
        macro_grid_name = "macro_grid_" + str(macro_inst.getName())
        macro_grids = pdngen.findGrid(macro_grid_name)
        if macro_grids:
            # Assuming only one grid object per instance name
            macro_grid = macro_grids[0]
            # Create straps on metal5 for macro connections
            pdngen.makeStrap(grid = macro_grid,
                layer = m5,
                width = micron_to_dbu(macro_m5_width),
                spacing = micron_to_dbu(macro_m5_spacing),
                pitch = micron_to_dbu(macro_m5_pitch),
                offset = micron_to_dbu(0),
                number_of_straps = 0,
                snap = True, # Snap to grid
                starts_with = pdn.GRID,
                extend = pdn.CORE,
                nets = [])
            # Create straps on metal6 for macro connections
            pdngen.makeStrap(grid = macro_grid,
                layer = m6,
                width = micron_to_dbu(macro_m6_width),
                spacing = micron_to_dbu(macro_m6_spacing),
                pitch = micron_to_dbu(macro_m6_pitch),
                offset = micron_to_dbu(0),
                number_of_straps = 0,
                snap = True,
                starts_with = pdn.GRID,
                extend = pdn.CORE,
                nets = [])

            # Create via connections between macro power grid layers and core layers
            # Connect M4 (core grid) to M5 (macro grid)
            pdngen.makeConnect(grid = macro_grid,
                layer0 = m4,
                layer1 = m5,
                cut_pitch_x = micron_to_dbu(via_pitch_x),
                cut_pitch_y = micron_to_dbu(via_pitch_y),
                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
            # Connect M5 to M6 (macro grid layers)
            pdngen.makeConnect(grid = macro_grid,
                layer0 = m5,
                layer1 = m6,
                cut_pitch_x = micron_to_dbu(via_pitch_x),
                cut_pitch_y = micron_to_dbu(via_pitch_y),
                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
            # Connect M6 (macro grid) to M7 (core grid)
            pdngen.makeConnect(grid = macro_grid,
                layer0 = m6,
                layer1 = m7,
                cut_pitch_x = micron_to_dbu(via_pitch_x),
                cut_pitch_y = micron_to_dbu(via_pitch_y),
                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
        else:
             print(f"Warning: Macro instance grid '{macro_grid_name}' not found after creation attempt.")


# Generate and write the power delivery network
pdngen.checkSetup() # Verify configuration
pdngen.buildGrids(False) # Build the power grid shapes in memory
pdngen.writeToDb(True) # Write power grid shapes to the design database
pdngen.resetShapes() # Reset temporary shapes


# Macro Placement (if macros exist)
if len(macros) > 0:
    print("Design contains macros. Performing macro placement.")
    mpl = design.getMacroPlacer()
    # Set the fence region for macro placement
    # The place method uses fence_lx, fence_ly, fence_ux, fence_uy parameters in microns
    # Set halo around macros during placement to maintain minimum distance
    mpl.place(
        num_threads = 0, # Use default/all threads
        max_num_macro = 0, # Place all macros
        min_num_macro = 0,
        max_num_inst = 0,
        min_num_inst = 0,
        tolerance = 0.1,
        max_num_level = 2,
        coarsening_ratio = 10.0,
        large_net_threshold = 50,
        signature_net_threshold = 50,
        halo_width = macro_halo_width,
        halo_height = macro_halo_height,
        fence_lx = macro_fence_lx,
        fence_ly = macro_fence_ly,
        fence_ux = macro_fence_ux,
        fence_uy = macro_fence_uy,
        area_weight = 0.1,
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        pin_access_th = 0.0,
        target_util = 0.25, # Example utilization target
        target_dead_space = 0.05, # Example dead space target
        min_ar = 0.33, # Example minimum aspect ratio
        snap_layer = 0, # 0 means no snap, can be set to a layer level if needed
        bus_planning_flag = False,
        report_directory = ""
    )
else:
    print("No macros found. Skipping macro placement.")


# Global Placement
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Not timing-driven in this request
gpl.setRoutabilityDrivenMode(True)
gpl.setUniformTargetDensityMode(True)
# Run global placement steps
gpl.doInitialPlace(threads = 0) # Use default/all threads
gpl.doNesterovPlace(threads = 0)
gpl.reset()

# Initial Detailed Placement
opendp = design.getOpendp()
# Remove filler cells before detailed placement if they exist
# Note: Need to identify filler cell masters first if they were added.
# If no fillers were added yet, this command might do nothing.
# A safer approach is to remove fillers just before the FINAL detailed placement after fillers are added.
# Let's skip removing fillers here as they haven't been added yet.

# Get displacement in DBU
max_disp_x_dbu = micron_to_dbu(detailed_placement_max_disp_x)
max_disp_y_dbu = micron_to_dbu(detailed_placement_max_disp_y)
# Perform initial detailed placement
# The parameters are max_disp_x (DBU), max_disp_y (DBU), filler_lib_str, incremental_flag
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)


# Clock Tree Synthesis (CTS)
cts = design.getTritonCts()
# Set clock nets to be synthesized
cts.setClockNets(clock_net_name)
# Set clock buffers
cts.setBufferList("BUF_X2") # Available buffer cells list
cts.setRootBuffer("BUF_X2") # Buffer at the clock root
cts.setSinkBuffer("BUF_X2") # Buffer near clock sinks
# Run CTS
cts.runTritonCts()


# Final Detailed Placement (after CTS)
# Insert filler cells before final detailed placement to fill gaps
# Need to find filler cell masters
filler_masters = list()
# Iterate through libraries to find CORE_SPACER masters
for lib in design.getDb().getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

if len(filler_masters) > 0:
    # Add filler cells
    opendp.fillerPlacement(filler_masters = filler_masters,
                                     prefix = "FILLCELL_", # Prefix for new filler instance names
                                     verbose = False)
    print(f"Inserted {len(design.getBlock().getInsts()) - len(macros) - opendp.numNonFillerCells()} filler cells.")
    # Remove filler cells to allow detailed placement to move cells including fillers
    # This step is sometimes done if fillers are added before DP that might need adjustment
    # opendp.removeFillers() # Uncomment if fillers need to be removed and re-added/placed later

# Perform final detailed placement
# Use the same displacement settings as initial DP
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)


# IR Drop Analysis and Power Reporting
# Note: IR Drop Analysis (e.g., using IRDrop tool) and detailed Power Reporting (e.g., using OpenSTA power analysis)
# require specific tools/integrations not fully exposed or demonstrated in the provided API examples.
# Therefore, these steps cannot be implemented using the provided context.
#
print("Skipping IR Drop Analysis and Power Reporting: APIs not available in provided context.")


# Routing
# Get routing layers from technology database
tech = design.getTech().getDB().getTech()
m1_layer = tech.findLayer("metal1")
m7_layer = tech.findLayer("metal7")

if not m1_layer or not m7_layer:
    print("Error: Could not find metal1 or metal7 layer for routing. Exiting.")
    exit()

min_routing_layer_level = m1_layer.getRoutingLevel()
max_routing_layer_level = m7_layer.getRoutingLevel()

# Global Routing
grt = design.getGlobalRouter()
# Set routing layer range for global routing
grt.setMinRoutingLayer(min_routing_layer_level)
grt.setMaxRoutingLayer(max_routing_layer_level)
# Set routing layer range for clock nets (same as signal nets per prompt requirement)
grt.setMinLayerForClock(min_routing_layer_level)
grt.setMaxLayerForClock(max_routing_layer_level)
grt.setAdjustment(0.5) # Default congestion adjustment
grt.setVerbose(True)
# Run global routing. The number of iterations (20 as per prompt) is not a direct parameter
# in the provided `globalRoute` API example. This may be an internal parameter or set via Tcl.
grt.globalRoute(True) # True enables writing output (guides, etc.)


# Detailed Routing
drter = design.getTritonRoute()
params = drt.ParamStruct()
# Set routing layer range for detailed routing
params.bottomRoutingLayer = "metal1"
params.topRoutingLayer = "metal7"
params.verbose = 1
params.cleanPatches = True
params.doPa = True # Perform post-routing pin access checks/fixes
params.singleStepDR = False
params.minAccessPoints = 1
params.enableViaGen = True
params.drouteEndIter = 1 # Default iterations, can be adjusted if needed
params.outputMazeFile = ""
params.outputDrcFile = ""
params.outputCmapFile = ""
params.outputGuideCoverageFile = ""
params.dbProcessNode = ""
params.viaInPinBottomLayer = ""
params.viaInPinTopLayer = ""
params.orSeed = -1
params.orK = 0
params.saveGuideUpdates = False

drter.setParams(params)
# Run detailed routing
drter.main()


# Write final DEF file
design.writeDef("final.def")