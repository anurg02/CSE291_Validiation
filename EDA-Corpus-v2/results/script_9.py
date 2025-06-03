import odb
import pdn
import openroad as ord

# Define micron to DBU conversion for clarity
def micronToDBU(microns):
    """Converts microns to design database units (DBU)."""
    return design.micronToDBU(microns)

# 1. Create Clock
# Create a clock signal on the "clk" port with a period of 50 ns (50000 ps)
clock_period_ns = 50
clock_period_ps = clock_period_ns * 1000
clock_port_name = "clk"
clock_name = "core_clock"
design.evalTclString(f"create_clock -period {clock_period_ps} [get_ports {clock_port_name}] -name {clock_name}")

# Propagate the newly created clock signal
design.evalTclString(f"set_propagated_clock [get_clocks {clock_name}]")

# Set unit resistance and capacitance for clock and signal nets for timing analysis (used by STA, though not explicitly run in this script)
design.evalTclString("set_wire_rc -clock -resistance 0.03574 -capacitance 0.07516")
design.evalTclString("set_wire_rc -signal -resistance 0.03574 -capacitance 0.07516")

# 2. Floorplanning
# Initialize floorplan using core utilization and die margin
# Target utilization is 40% (0.40)
# Spacing between core and die is 12 microns
target_utilization = 0.40
die_margin_microns = 12
design.evalTclString(f"init_floorplan -core_util {target_utilization} -core_margin {die_margin_microns}")

# Make placement tracks based on the initialized floorplan
floorplan = design.getFloorplan()
floorplan.makeTracks()

# Dump DEF file after floorplanning
design.writeDef("floorplan.def")

# 3. IO Pin Placement
# Configure and run I/O pin placement
io_placer_params = design.getIOPlacer().getParameters()
# Set minimum distance between pins to 0 (not required by prompt, but good practice)
io_placer_params.setMinDistance(micronToDBU(0))
io_placer_params.setCornerAvoidance(micronToDBU(0)) # Avoid corners
io_placer_params.setMinDistanceInTracks(False) # Use DBU for min distance

# Place I/O pins on metal8 (horizontal) and metal9 (vertical) layers
metal8_layer = design.getTech().getDB().getTech().findLayer("metal8")
metal9_layer = design.getTech().getDB().getTech().findLayer("metal9")
design.getIOPlacer().addHorLayer(metal8_layer)
design.getIOPlacer().addVerLayer(metal9_layer)

# Run I/O placement using annealing algorithm (random mode True)
design.getIOPlacer().runAnnealing(True)

# Dump DEF file after IO placement
design.writeDef("io_placed.def")

# 4. Macro Placement
# Place macro blocks if present
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
if len(macros) > 0:
    mpl = design.getMacroPlacer()
    # Set macro-to-macro spacing to 5 microns
    mpl.setMacroSpacing(micronToDBU(5))

    # The 'place' function parameters can configure macro halo and fence regions
    # Set halo around each macro to 5 microns
    halo_microns = 5
    mpl.place(
        num_threads = 64, # Example thread count
        max_num_macro = len(macros), # Place all macros
        min_num_macro = 0,
        max_num_inst = 0,
        min_num_inst = 0,
        tolerance = 0.1,
        max_num_level = 2,
        coarsening_ratio = 10.0,
        large_net_threshold = 50,
        signature_net_threshold = 50,
        halo_width = halo_microns, # Set halo width in microns
        halo_height = halo_microns, # Set halo height in microns
        # Fence region is typically the core area, no specific value given, use core
        fence_lx = design.block.dbuToMicrons(design.block.getCoreArea().xMin()),
        fence_ly = design.block.dbuToMicrons(design.block.getCoreArea().yMin()),
        fence_ux = design.block.dbuToMicrons(design.block.getCoreArea().xMax()),
        fence_uy = design.block.dbuToMicrons(design.block.getCoreArea().yMax()),
        area_weight = 0.1,
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        pin_access_th = 0.0,
        target_util = target_utilization, # Use the floorplan target utilization
        target_dead_space = 0.05, # Example value
        min_ar = 0.33, # Example aspect ratio constraint
        snap_layer = 4, # Snap macro pins on metal4 (as in example 1, though not requested here)
        bus_planning_flag = False,
        report_directory = "" # No report directory
    )

# Dump DEF file after macro placement
design.writeDef("macro_placed.def")

# 5. Standard Cell Placement (Global & Detailed)

# Configure and run global placement (Replace tool)
gpl = design.getReplace()
# Use default global placement settings or configure as needed
# gpl.setTimingDrivenMode(False) # Example setting
# gpl.setRoutabilityDrivenMode(True) # Example setting
# gpl.setUniformTargetDensityMode(True) # Example setting
# gpl.setInitialPlaceMaxIter(10) # Example iteration limit
# gpl.setInitDensityPenalityFactor(0.05) # Example penalty

# Run global placement
gpl.doInitialPlace(threads = 4) # Run initial placement
gpl.doNesterovPlace(threads = 4) # Run Nesterov-accelerated placement
gpl.reset() # Reset the global placer

# Run initial detailed placement (OpenDP tool)
# Remove filler cells before detailed placement if any exist (required by detailedPlacement API)
design.getOpendp().removeFillers()

# Set maximum displacement allowed in x and y directions to 0.5 microns
max_disp_x_microns = 0.5
max_disp_y_microns = 0.5
max_disp_x_dbu = micronToDBU(max_disp_x_microns)
max_disp_y_dbu = micronToDBU(max_disp_y_microns)

design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

# Dump DEF file after initial placement
design.writeDef("placed.def")

# 6. Clock Tree Synthesis (CTS)
# Configure and run clock tree synthesis (TritonCTS tool)
cts = design.getTritonCts()
# Set clock buffers to be used (BUF_X2)
cts.setBufferList("BUF_X2")
cts.setRootBuffer("BUF_X2")
cts.setSinkBuffer("BUF_X2")

# Run CTS
cts.runTritonCts()

# Dump DEF file after CTS
design.writeDef("cts.def")

# 7. Detailed Placement (Post-CTS)
# Run detailed placement again after CTS to legalize positions of inserted buffers
# Use the same maximum displacement settings as before (0.5 microns)
design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

# Dump DEF file after post-CTS detailed placement
design.writeDef("post_cts_placed.def")


# 8. Power Delivery Network (PDN) Generation
pdngen = design.getPdnGen()

# Set up global power/ground connections
# Mark power/ground nets as special nets if they exist
for net in design.getBlock().getNets():
    if net.getSigType() in ["POWER", "GROUND"]:
        net.setSpecial()

# Find existing power and ground nets or create if needed
vdd_net = design.getBlock().findNet("VDD")
vss_net = design.getBlock().findNet("VSS")

# Create VDD/VSS nets if they don't exist and set their signal type
if vdd_net is None:
    vdd_net = odb.dbNet_create(design.getBlock(), "VDD")
if vss_net is None:
    vss_net = odb.dbNet_create(design.getBlock(), "VSS")

# Ensure nets are marked as special and have correct signal type
vdd_net.setSpecial()
vdd_net.setSigType("POWER")
vss_net.setSpecial()
vss_net.setSigType("GROUND")

# Connect power pins to global nets for all instances
# This connects standard VDD/VSS pins of standard cells and macros
design.getBlock().addGlobalConnect(region = None,
    instPattern = ".*", # Apply to all instances
    pinPattern = "^VDD.*", # Connect pins starting with VDD
    net = vdd_net,
    do_connect = True)
design.getBlock().addGlobalConnect(region = None,
    instPattern = ".*", # Apply to all instances
    pinPattern = "^VSS.*", # Connect pins starting with VSS
    net = vss_net,
    do_connect = True)

# Apply the global connections
design.getBlock().globalConnect()

# Configure the core voltage domain with primary power/ground nets
pdngen.setCoreDomain(power = vdd_net,
    switched_power = None, # No switched power
    ground = vss_net,
    secondary = []) # No secondary nets

# Get voltage domains (assuming 'Core' domain exists after setCoreDomain)
domains = [pdngen.findDomain("Core")]

# Get routing layers for PDN implementation
m1 = design.getTech().getDB().getTech().findLayer("metal1")
m4 = design.getTech().getDB().getTech().findLayer("metal4")
m5 = design.getTech().getDB().getTech().findLayer("metal5")
m6 = design.getTech().getDB().getTech().findLayer("metal6")
m7 = design.getTech().getDB().getTech().findLayer("metal7")
m8 = design.getTech().getDB().getTech().findLayer("metal8")

# Via cut pitch between parallel grids is 0 um
via_cut_pitch_dbu = micronToDBU(0)
pdn_cut_pitch = [via_cut_pitch_dbu, via_cut_pitch_dbu]

# Offset for all PDN features is 0 um
pdn_offset_dbu = micronToDBU(0)
pdn_offset = [pdn_offset_dbu, pdn_offset_dbu, pdn_offset_dbu, pdn_offset_dbu] # For ring offset


# Create power grid for standard cells (on the core domain)
for domain in domains:
    # Create the main core grid structure named "top"
    pdngen.makeCoreGrid(domain = domain,
        name = "top",
        starts_with = pdn.GROUND, # Start grid pattern with ground
        pin_layers = [], # No specific pin layers
        generate_obstructions = [], # No specific obstruction layers
        powercell = None, # No power cell
        powercontrol = None, # No power control cell
        powercontrolnetwork = "STAR") # Star network type

# Get the core grid object
core_grid = pdngen.findGrid("top")

# Add PDN features to the core grid for standard cells
if core_grid:
    for g in core_grid:
        # Add M1 followpin straps (follow standard cell pin pattern)
        pdngen.makeFollowpin(grid = g,
            layer = m1,
            width = micronToDBU(0.07), # M1 width: 0.07 um
            extend = pdn.CORE) # Extend within the core area

        # Add M4 straps
        pdngen.makeStrap(grid = g,
            layer = m4,
            width = micronToDBU(1.2), # M4 width: 1.2 um
            spacing = micronToDBU(1.2), # M4 spacing: 1.2 um
            pitch = micronToDBU(6), # M4 pitch: 6 um
            offset = pdn_offset_dbu, # Offset: 0 um
            number_of_straps = 0, # Auto-calculate number
            snap = True, # Snap to grid
            starts_with = pdn.GRID, # Start pattern based on grid origin
            extend = pdn.CORE, # Extend within core
            nets = []) # Apply to default nets (VDD/VSS)

        # Add M7 straps
        pdngen.makeStrap(grid = g,
            layer = m7,
            width = micronToDBU(1.4), # M7 width: 1.4 um
            spacing = micronToDBU(1.4), # M7 spacing: 1.4 um
            pitch = micronToDBU(10.8), # M7 pitch: 10.8 um
            offset = pdn_offset_dbu, # Offset: 0 um
            number_of_straps = 0,
            snap = True,
            starts_with = pdn.GRID,
            extend = pdn.CORE,
            nets = [])

        # Add M7 and M8 power rings around the core boundary
        # M7 ring: width 4 um, spacing 4 um
        # M8 ring: width 4 um, spacing 4 um
        pdngen.makeRing(grid = g,
            layer0 = m7, # Inner layer M7
            width0 = micronToDBU(4), # M7 width: 4 um
            spacing0 = micronToDBU(4), # M7 spacing: 4 um
            layer1 = m8, # Outer layer M8
            width1 = micronToDBU(4), # M8 width: 4 um
            spacing1 = micronToDBU(4), # M8 spacing: 4 um
            starts_with = pdn.GRID, # Start pattern based on grid origin
            offset = pdn_offset, # Offset: 0 um [left, bottom, right, top]
            pad_offset = pdn_offset, # Pad offset: 0 um
            extend = False, # Do not extend rings beyond their defined area
            pad_pin_layers = [], # No specific pad layers
            nets = []) # Apply to default nets (VDD/VSS)

        # Add via connections between core grid layers
        # Connect M1 to M4
        pdngen.makeConnect(grid = g,
            layer0 = m1, layer1 = m4,
            cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1], # Via cut pitch: 0 um
            vias = [], techvias = [],
            max_rows = 0, max_columns = 0,
            ongrid = [], split_cuts = {}, dont_use_vias = "")
        # Connect M4 to M7
        pdngen.makeConnect(grid = g,
            layer0 = m4, layer1 = m7,
            cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1], # Via cut pitch: 0 um
            vias = [], techvias = [],
            max_rows = 0, max_columns = 0,
            ongrid = [], split_cuts = {}, dont_use_vias = "")
        # Connect M7 to M8
        pdngen.makeConnect(grid = g,
            layer0 = m7, layer1 = m8,
            cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1], # Via cut pitch: 0 um
            vias = [], techvias = [],
            max_rows = 0, max_columns = 0,
            ongrid = [], split_cuts = {}, dont_use_vias = "")


# Create power grid for macro blocks if present
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
if len(macros) > 0:
    macro_halo_dbu = [micronToDBU(5) for i in range(4)] # 5 um halo around macros

    for i, macro_inst in enumerate(macros):
        # Create separate power grid for each macro instance
        for domain in domains:
            pdngen.makeInstanceGrid(domain = domain,
                name = f"CORE_macro_grid_{i}", # Unique name for each macro grid
                starts_with = pdn.GROUND, # Start pattern with ground
                inst = macro_inst, # Target macro instance
                halo = macro_halo_dbu, # Halo around macro: 5 um
                pg_pins_to_boundary = True, # Connect PG pins to boundary
                default_grid = False, # Not the default grid
                generate_obstructions = [],
                is_bump = False)

        # Get the instance grid object for the current macro
        macro_grid = pdngen.findGrid(f"CORE_macro_grid_{i}")

        if macro_grid:
            for g in macro_grid:
                # Add M5 straps for macro connections
                pdngen.makeStrap(grid = g,
                    layer = m5,
                    width = micronToDBU(1.2), # M5 width: 1.2 um
                    spacing = micronToDBU(1.2), # M5 spacing: 1.2 um
                    pitch = micronToDBU(6), # M5 pitch: 6 um
                    offset = pdn_offset_dbu, # Offset: 0 um
                    number_of_straps = 0,
                    snap = True, # Snap to grid
                    starts_with = pdn.GRID,
                    extend = pdn.CORE, # Extend within core (or RINGS)
                    nets = []) # Apply to default nets (VDD/VSS)

                # Add M6 straps for macro connections
                pdngen.makeStrap(grid = g,
                    layer = m6,
                    width = micronToDBU(1.2), # M6 width: 1.2 um
                    spacing = micronToDBU(1.2), # M6 spacing: 1.2 um
                    pitch = micronToDBU(6), # M6 pitch: 6 um
                    offset = pdn_offset_dbu, # Offset: 0 um
                    number_of_straps = 0,
                    snap = True,
                    starts_with = pdn.GRID,
                    extend = pdn.CORE, # Extend within core (or RINGS)
                    nets = [])

                # Add M5 and M6 power rings around the macro instance
                # M5 ring: width 1.5 um, spacing 1.5 um
                # M6 ring: width 1.5 um, spacing 1.5 um
                pdngen.makeRing(grid = g,
                    layer0 = m5, # Inner layer M5
                    width0 = micronToDBU(1.5), # M5 width: 1.5 um
                    spacing0 = micronToDBU(1.5), # M5 spacing: 1.5 um
                    layer1 = m6, # Outer layer M6
                    width1 = micronToDBU(1.5), # M6 width: 1.5 um
                    spacing1 = micronToDBU(1.5), # M6 spacing: 1.5 um
                    starts_with = pdn.GRID,
                    offset = pdn_offset, # Offset: 0 um
                    pad_offset = pdn_offset, # Pad offset: 0 um
                    extend = False, # Do not extend rings
                    pad_pin_layers = [],
                    nets = [])

                # Add via connections between macro power grid layers
                # Connect M4 (from core grid) to M5 (macro grid)
                pdngen.makeConnect(grid = g,
                    layer0 = m4, layer1 = m5,
                    cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1], # Via cut pitch: 0 um
                    vias = [], techvias = [],
                    max_rows = 0, max_columns = 0,
                    ongrid = [], split_cuts = {}, dont_use_vias = "")
                # Connect M5 to M6 (macro grid layers)
                pdngen.makeConnect(grid = g,
                    layer0 = m5, layer1 = m6,
                    cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1], # Via cut pitch: 0 um
                    vias = [], techvias = [],
                    max_rows = 0, max_columns = 0,
                    ongrid = [], split_cuts = {}, dont_use_vias = "")
                # Connect M6 (macro grid) to M7 (core grid)
                pdngen.makeConnect(grid = g,
                    layer0 = m6, layer1 = m7,
                    cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1], # Via cut pitch: 0 um
                    vias = [], techvias = [],
                    max_rows = 0, max_columns = 0,
                    ongrid = [], split_cuts = {}, dont_use_vias = "")


# Verify PDN setup
pdngen.checkSetup()
# Build the power grid (False means do not trim/clean up)
pdngen.buildGrids(False)
# Write the generated PDN to the design database (add_pins = True)
pdngen.writeToDb(True, "") # "" for no report file
# Reset temporary shapes used during generation
pdngen.resetShapes()

# Dump DEF file after PDN generation
design.writeDef("pdn.def")

# 9. Global Routing
# Configure and run global routing
grt = design.getGlobalRouter()

# Determine routing layers - use all available routing layers from M1 upwards
tech = design.getTech().getDB().getTech()
min_routing_layer = None
max_routing_layer = None
for layer in tech.getLayers():
    if layer.getType() == "ROUTING":
        level = layer.getRoutingLevel()
        if min_routing_layer is None or level < min_routing_layer:
            min_routing_layer = level
        if max_routing_layer is None or level > max_routing_layer:
            max_routing_layer = level

if min_routing_layer is not None and max_routing_layer is not None:
    grt.setMinRoutingLayer(min_routing_layer)
    grt.setMaxRoutingLayer(max_routing_layer)
    # Set the same layer range for clock nets
    grt.setMinLayerForClock(min_routing_layer)
    grt.setMaxLayerForClock(max_routing_layer)
else:
     print("Warning: No routing layers found. Skipping Global Routing layer configuration.")

# Set routing adjustment (default is 0.5)
# grt.setAdjustment(0.5) # Using default

# Run global routing with specified iterations (20 times) using Tcl command
# The Python API does not directly expose the iteration count parameter for globalRoute()
design.evalTclString("global_route -iterations 20")

# Dump DEF file after global routing
design.writeDef("global_routed.def")

# 10. Insert Filler Cells
# Find filler cell masters in the library
filler_masters = list()
filler_cells_prefix = "FILLCELL_" # Common naming convention prefix
db = ord.get_db()
for lib in db.getLibs():
    for master in lib.getMasters():
        # Assuming filler cells have CORE_SPACER type
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

# If filler cells are found, insert them
if len(filler_masters) > 0:
    design.getOpendp().fillerPlacement(filler_masters = filler_masters,
                                     prefix = filler_cells_prefix,
                                     verbose = False)
else:
    print("Warning: No filler cells found in library. Skipping filler insertion.")

# 11. Save Final Outputs
# Write the final design database to file
design.writeDb("final.odb")

# Write the final Verilog netlist
design.evalTclString("write_verilog final.v")