import odb
import pdn
import drt
import openroad as ord

# Assume design is already loaded with LEF and Verilog
# Example:
# design.readLef("path/to/tech.lef")
# design.readLef("path/to/cells.lef")
# design.readVerilog("path/to/synthesized.v")
# design.linkDesign("top_module_name")

# Set the clock signal
# Create a clock signal on the port "clk" with a period of 20 ns and name it "core_clock"
clock_period_ns = 20
clock_period_ps = clock_period_ns * 1000
port_name = "clk"
clock_name = "core_clock"
design.evalTclString(f"create_clock -period {clock_period_ps} [get_ports {port_name}] -name {clock_name}")

# Propagate the clock signal
design.evalTclString("set_propagated_clock [all_clocks]")

# Initialize floorplan
floorplan = design.getFloorplan()

# Define die area (0,0) to (45,45) um
die_llx_micron = 0
die_lly_micron = 0
die_urx_micron = 45
die_ury_micron = 45
die_area = odb.Rect(design.micronToDBU(die_llx_micron), design.micronToDBU(die_lly_micron),
                    design.micronToDBU(die_urx_micron), design.micronToDBU(die_ury_micron))

# Define core area (5,5) to (40,40) um
core_llx_micron = 5
core_lly_micron = 5
core_urx_micron = 40
core_ury_micron = 40
core_area = odb.Rect(design.micronToDBU(core_llx_micron), design.micronToDBU(core_lly_micron),
                     design.micronToDBU(core_urx_micron), design.micronToDBU(core_ury_micron))

# Find a site definition (assuming a site like "FreePDK45_38x28_10R_NP_162NW_34O" exists)
# Replace with the actual site name from your technology LEF
site = floorplan.findSite("FreePDK45_38x28_10R_NP_162NW_34O")
if not site:
    print("Error: Could not find required site. Please check your LEF files.")
    # Exit or handle error appropriately
    exit()

# Initialize the floorplan with die and core areas and the site
floorplan.initFloorplan(die_area, core_area, site)

# Create placement rows based on the core area and site
floorplan.makeTracks() # This usually makes tracks too, but calling makeRows explicitly might be needed depending on flow
# floorplan.makeRows() # Explicitly create rows if needed

# Perform macro placement if macros exist
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
if len(macros) > 0:
    mpl = design.getMacroPlacer()
    block = design.getBlock()

    # Define macro fence region (5,5) to (20,25) um
    fence_lx_micron = 5.0
    fence_ly_micron = 5.0
    fence_ux_micron = 20.0
    fence_uy_micron = 25.0

    # Set halo around macros (5 um)
    halo_width_micron = 5.0
    halo_height_micron = 5.0

    # Macro placement requires global placement stage objects, but mpl.place handles its own optimization
    # Set placement parameters including fence and halo
    mpl.place(
        # Use 64 threads for placement
        num_threads = 64,
        # Set fence region for macros
        fence_lx = fence_lx_micron,
        fence_ly = fence_ly_micron,
        fence_ux = fence_ux_micron,
        fence_uy = fence_uy_micron,
        # Set halo around macros
        halo_width = halo_width_micron,
        halo_height = halo_height_micron,
        # Add other parameters as needed for control (e.g., target utilization, weights)
        # The prompt doesn't specify min distance between macros directly in the API,
        # but halo helps push other cells away.
        # min_macro_macro_dist = design.micronToDBU(5.0), # This parameter doesn't seem to exist in this API call
        # Default values are used for unspecified parameters
    )
    print(f"Placed {len(macros)} macros.")
else:
    print("No macros found for macro placement.")


# Configure and run global placement
gpl = design.getReplace()
# Set timing and routability driven modes (common settings)
gpl.setTimingDrivenMode(True)
gpl.setRoutabilityDrivenMode(True)
# Set uniform target density (common setting)
gpl.setUniformTargetDensityMode(True)
# Set the number of initial place iterations (as requested 10 times)
gpl.setInitialPlaceMaxIter(10)
# Run initial placement
gpl.doInitialPlace(threads = 4)
# Run Nesterov-based global placement
gpl.doNesterovPlace(threads = 4)
# Reset global placement engine
gpl.reset()
print("Global placement finished.")

# Run initial detailed placement (pre-CTS)
# Get the site dimensions for DBU calculation
site = design.getBlock().getRows()[0].getSite()
# Set maximum displacement at x-axis (1 um) and y-axis (3 um)
max_disp_x_micron = 1.0
max_disp_y_micron = 3.0
max_disp_x_dbu = int(design.micronToDBU(max_disp_x_micron))
max_disp_y_dbu = int(design.micronToDBU(max_disp_y_micron)) # Note: Opendp detailedPlacement takes DBU directly for displacement

# Remove filler cells before detailed placement if any were previously inserted
design.getOpendp().removeFillers()
# Perform detailed placement
design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Initial detailed placement finished.")


# Configure power delivery network (PDN)
import pdn, odb

# Set up global power/ground connections
# Mark power/ground nets as special nets
block = design.getBlock()
for net in block.getNets():
    if net.getSigType() == "POWER" or net.getSigType() == "GROUND":
        net.setSpecial()

# Find or create VDD/VSS nets
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

# Create VDD/VSS nets if they don't exist
if VDD_net == None:
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSigType("POWER")
    VDD_net.setSpecial()
if VSS_net == None:
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSigType("GROUND")
    VSS_net.setSpecial()

# Apply global connections to connect standard cell pins to power/ground nets
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
block.globalConnect()

# Configure power domains
pdngen = design.getPdnGen()
# Set core power domain with primary power/ground nets
pdngen.setCoreDomain(power = VDD_net, switched_power = None, ground = VSS_net, secondary = [])

# Set via cut pitch to 0 um as requested
pdn_cut_pitch_x = design.micronToDBU(0)
pdn_cut_pitch_y = design.micronToDBU(0)

# Get metal layers for power grid implementation
tech = design.getTech().getDB().getTech()
m1 = tech.findLayer("metal1")
m4 = tech.findLayer("metal4")
m5 = tech.findLayer("metal5") # For macro grid
m6 = tech.findLayer("metal6") # For macro grid
m7 = tech.findLayer("metal7")
m8 = tech.findLayer("metal8")

# Create core grid
domains = [pdngen.findDomain("Core")]
if len(domains) == 0:
    print("Error: Core domain not found. Cannot build PDN.")
    # Exit or handle error appropriately
    exit()

core_domain = domains[0]
# Define halo around macros for core grid exclusion (optional but good practice)
# Using the same halo value as macro placement for consistency
core_grid_halo = [design.micronToDBU(halo_width_micron), design.micronToDBU(halo_height_micron),
                  design.micronToDBU(halo_width_micron), design.micronToDBU(halo_height_micron)]


# Create the main core grid structure
pdngen.makeCoreGrid(domain = core_domain,
    name = "core_grid",
    starts_with = pdn.GROUND, # Start with ground net (can be POWER or GRID too)
    pin_layers = [], # Layers for connecting to top-level pins (e.g., pad connections)
    generate_obstructions = [],
    powercell = None, # Power gate cell, not used here
    powercontrol = None,
    powercontrolnetwork = "STAR",
    # Add halo to exclude regions around macros if desired
    halo = core_grid_halo
    )

core_grid = pdngen.findGrid("core_grid")
if not core_grid:
     print("Error: Failed to create core grid.")
     exit()


# Add power rings to the core grid
# M7 ring: width 2 um, spacing 2 um, offset 0 um
pdngen.makeRing(grid = core_grid,
    layer0 = m7,
    width0 = design.micronToDBU(2.0),
    spacing0 = design.micronToDBU(2.0),
    layer1 = m8, # M8 ring: width 2 um, spacing 2 um
    width1 = design.micronToDBU(2.0),
    spacing1 = design.micronToDBU(2.0),
    starts_with = pdn.GRID, # Start based on the grid pattern (e.g., GR/PW)
    offset = [design.micronToDBU(0) for i in range(4)], # Offset 0 um
    pad_offset = [design.micronToDBU(0) for i in range(4)],
    extend = pdn.CORE, # Extend to core boundary
    pad_pin_layers = [],
    nets = [])
print("Added PDN rings on M7 and M8.")

# Add straps to the core grid
# M1 followpin: width 0.07 um
pdngen.makeFollowpin(grid = core_grid,
    layer = m1,
    width = design.micronToDBU(0.07),
    extend = pdn.CORE) # Extend to core boundary
print("Added M1 followpin straps.")

# M4 strap: width 1.2 um, spacing 1.2 um, pitch 6 um, offset 0 um
pdngen.makeStrap(grid = core_grid,
    layer = m4,
    width = design.micronToDBU(1.2),
    spacing = design.micronToDBU(1.2),
    pitch = design.micronToDBU(6),
    offset = design.micronToDBU(0), # Offset 0 um
    number_of_straps = 0, # Auto-calculate
    snap = False, # Don't snap to grid
    starts_with = pdn.GRID,
    extend = pdn.CORE, # Extend to core boundary
    nets = [])
print("Added M4 straps.")

# M7 strap: width 1.4 um, spacing 1.4 um, pitch 10.8 um, offset 0 um
pdngen.makeStrap(grid = core_grid,
    layer = m7,
    width = design.micronToDBU(1.4),
    spacing = design.micronToDBU(1.4),
    pitch = design.micronToDBU(10.8),
    offset = design.micronToDBU(0), # Offset 0 um
    number_of_straps = 0,
    snap = False,
    starts_with = pdn.GRID,
    extend = pdn.CORE, # Extend to core boundary
    nets = [])
print("Added M7 straps.")

# M8 strap: width 1.4 um, spacing 1.4 um, pitch 10.8 um, offset 0 um
pdngen.makeStrap(grid = core_grid,
    layer = m8,
    width = design.micronToDBU(1.4),
    spacing = design.micronToDBU(1.4),
    pitch = design.micronToDBU(10.8),
    offset = design.micronToDBU(0), # Offset 0 um
    number_of_straps = 0,
    snap = False,
    starts_with = pdn.GRID,
    extend = pdn.CORE, # Extend to core boundary
    nets = [])
print("Added M8 straps.")

# Add via connections between core grid layers
# Connect M1 to M4
pdngen.makeConnect(grid = core_grid,
    layer0 = m1,
    layer1 = m4,
    cut_pitch_x = pdn_cut_pitch_x, # Via pitch 0 um
    cut_pitch_y = pdn_cut_pitch_y, # Via pitch 0 um
    vias = [], techvias = [],
    max_rows = 0, max_columns = 0, ongrid = [],
    split_cuts = dict(), dont_use_vias = "")
print("Added M1-M4 via connections.")

# Connect M4 to M7
pdngen.makeConnect(grid = core_grid,
    layer0 = m4,
    layer1 = m7,
    cut_pitch_x = pdn_cut_pitch_x, # Via pitch 0 um
    cut_pitch_y = pdn_cut_pitch_y, # Via pitch 0 um
    vias = [], techvias = [],
    max_rows = 0, max_columns = 0, ongrid = [],
    split_cuts = dict(), dont_use_vias = "")
print("Added M4-M7 via connections.")

# Connect M7 to M8
pdngen.makeConnect(grid = core_grid,
    layer0 = m7,
    layer1 = m8,
    cut_pitch_x = pdn_cut_pitch_x, # Via pitch 0 um
    cut_pitch_y = pdn_cut_pitch_y, # Via pitch 0 um
    vias = [], techvias = [],
    max_rows = 0, max_columns = 0, ongrid = [],
    split_cuts = dict(), dont_use_vias = "")
print("Added M7-M8 via connections.")

# Create instance grids for macros if they exist
if len(macros) > 0:
    for i, macro_inst in enumerate(macros):
        macro_grid_name = f"macro_grid_{i}"
        pdngen.makeInstanceGrid(domain = core_domain,
            name = macro_grid_name,
            starts_with = pdn.GROUND, # Or pdn.POWER depending on macro pin name
            inst = macro_inst,
            halo = [design.micronToDBU(0) for i in range(4)], # No halo needed for instance grid itself
            pg_pins_to_boundary = True, # Connect macro PG pins to grid boundary
            default_grid = False,
            generate_obstructions = [],
            is_bump = False)

        macro_grid = pdngen.findGrid(macro_grid_name)
        if macro_grid:
            # Add straps to the macro grid
            # M5 strap: width 1.2 um, spacing 1.2 um, pitch 6 um, offset 0 um
            pdngen.makeStrap(grid = macro_grid,
                layer = m5,
                width = design.micronToDBU(1.2),
                spacing = design.micronToDBU(1.2),
                pitch = design.micronToDBU(6),
                offset = design.micronToDBU(0), # Offset 0 um
                number_of_straps = 0,
                snap = True, # Snap to grid
                starts_with = pdn.GRID,
                extend = pdn.CORE, # Extend within the macro boundary (relative to instance grid)
                nets = [])
            print(f"Added M5 straps for macro {macro_inst.getName()}.")

            # M6 strap: width 1.2 um, spacing 1.2 um, pitch 6 um, offset 0 um
            pdngen.makeStrap(grid = macro_grid,
                layer = m6,
                width = design.micronToDBU(1.2),
                spacing = design.micronToDBU(1.2),
                pitch = design.micronToDBU(6),
                offset = design.micronToDBU(0), # Offset 0 um
                number_of_straps = 0,
                snap = True,
                starts_with = pdn.GRID,
                extend = pdn.CORE, # Extend within the macro boundary
                nets = [])
            print(f"Added M6 straps for macro {macro_inst.getName()}.")

            # Add via connections between macro grid layers and core grid layers
            # Connect M4 (core grid) to M5 (macro grid)
            pdngen.makeConnect(grid = macro_grid,
                layer0 = m4,
                layer1 = m5,
                cut_pitch_x = pdn_cut_pitch_x, # Via pitch 0 um
                cut_pitch_y = pdn_cut_pitch_y, # Via pitch 0 um
                vias = [], techvias = [],
                max_rows = 0, max_columns = 0, ongrid = [],
                split_cuts = dict(), dont_use_vias = "")
            print(f"Added M4-M5 via connections for macro {macro_inst.getName()}.")

            # Connect M5 to M6 (macro grid layers)
            pdngen.makeConnect(grid = macro_grid,
                layer0 = m5,
                layer1 = m6,
                cut_pitch_x = pdn_cut_pitch_x, # Via pitch 0 um
                cut_pitch_y = pdn_cut_pitch_y, # Via pitch 0 um
                vias = [], techvias = [],
                max_rows = 0, max_columns = 0, ongrid = [],
                split_cuts = dict(), dont_use_vias = "")
            print(f"Added M5-M6 via connections for macro {macro_inst.getName()}.")

            # Connect M6 (macro grid) to M7 (core grid)
            pdngen.makeConnect(grid = macro_grid,
                layer0 = m6,
                layer1 = m7,
                cut_pitch_x = pdn_cut_pitch_x, # Via pitch 0 um
                cut_pitch_y = pdn_cut_pitch_y, # Via pitch 0 um
                vias = [], techvias = [],
                max_rows = 0, max_columns = 0, ongrid = [],
                split_cuts = dict(), dont_use_vias = "")
            print(f"Added M6-M7 via connections for macro {macro_inst.getName()}.")


# Generate the final power delivery network
pdngen.checkSetup() # Verify PDN configuration
pdngen.buildGrids(False) # Build the power grid shapes
pdngen.writeToDb(True) # Write PDN shapes to the design database
pdngen.resetShapes() # Reset temporary shapes used during build
print("PDN generation finished.")


# Configure and run clock tree synthesis (CTS)
cts = design.getTritonCts()

# Set clock net to be synthesized
cts.setClockNets(clock_name)
# Set unit resistance and capacitance for clock and signal nets
design.evalTclString(f"set_wire_rc -clock -resistance 0.03574 -capacitance 0.07516")
design.evalTclString(f"set_wire_rc -signal -resistance 0.03574 -capacitance 0.07516")

# Set buffer list, root buffer, and sink buffer
cts.setBufferList("BUF_X2")
cts.setRootBuffer("BUF_X2")
cts.setSinkBuffer("BUF_X2")

# Run CTS
cts.runTritonCts()
print("CTS finished.")

# Run final detailed placement (post-CTS cleanup)
# Get the site dimensions for DBU calculation
site = design.getBlock().getRows()[0].getSite()
# Set maximum displacement at x-axis (1 um) and y-axis (3 um)
max_disp_x_micron = 1.0
max_disp_y_micron = 3.0
max_disp_x_dbu = int(design.micronToDBU(max_disp_x_micron))
max_disp_y_dbu = int(design.micronToDBU(max_disp_y_micron))

# Remove filler cells before detailed placement if any were previously inserted
design.getOpendp().removeFillers()
# Perform detailed placement
design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Post-CTS detailed placement finished.")

# Insert filler cells to fill empty spaces
db = ord.get_db()
filler_masters = list()
# Find filler cell masters (assuming CORE_SPACER type)
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

if len(filler_masters) == 0:
    print("No filler cells found in library. Skipping filler placement.")
else:
    # Define prefix for filler cell instance names
    filler_cells_prefix = "FILLCELL_"
    # Perform filler placement
    design.getOpendp().fillerPlacement(filler_masters = filler_masters,
                                     prefix = filler_cells_prefix,
                                     verbose = False)
    print("Filler placement finished.")


# Configure and run global routing
grt = design.getGlobalRouter()

# Get routing layers by name
min_route_layer_name = "metal1"
max_route_layer_name = "metal7"
min_route_layer = tech.findLayer(min_route_layer_name)
max_route_layer = tech.findLayer(max_route_layer_name)

if not min_route_layer or not max_route_layer:
     print(f"Error: Could not find routing layers {min_route_layer_name} or {max_route_layer_name}.")
     exit()

# Set min/max routing layers for signal and clock nets
grt.setMinRoutingLayer(min_route_layer.getRoutingLevel())
grt.setMaxRoutingLayer(max_route_layer.getRoutingLevel())
grt.setMinLayerForClock(min_route_layer.getRoutingLevel())
grt.setMaxLayerForClock(max_route_layer.getRoutingLevel())

# Other global router settings (optional)
grt.setAdjustment(0.5) # Example adjustment
grt.setVerbose(True)

# Run global routing (True means write results back to DB)
grt.globalRoute(True)
print("Global routing finished.")

# Configure and run detailed routing
drter = design.getTritonRoute()
params = drt.ParamStruct()

# Set minimum and maximum routing layers for detailed router
params.bottomRoutingLayer = min_route_layer_name
params.topRoutingLayer = max_route_layer_name

# Enable via generation
params.enableViaGen = True
# Set number of detailed routing iterations (e.g., 1)
params.drouteEndIter = 1
# Set verbose output
params.verbose = 1
# Clean patches after routing
params.cleanPatches = True
# Perform pin access analysis
params.doPa = True
# Disable single step DR
params.singleStepDR = False
# Set minimum access points
params.minAccessPoints = 1

# Set parameters for detailed router
drter.setParams(params)

# Run detailed routing
drter.main()
print("Detailed routing finished.")

# Write final DEF file
design.writeDef("final_placed_routed.def")
print("Wrote final_placed_routed.def")

# Write final Verilog file (post-placement/routing netlist)
# This usually includes buffer insertions from CTS and potentially tie-hi/low cells
design.evalTclString("write_verilog final_routed.v")
print("Wrote final_routed.v")

# Optional: Write SPEF file for extraction (requires RC data setup)
# design.evalTclString("write_spef final.spef")
# print("Wrote final.spef")