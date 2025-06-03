import odb
import pdn
import drt
import openroad as ord

# --- Clock Setup ---
# Define clock parameters
clock_period_ns = 20
clock_period_ps = clock_period_ns * 1000
port_name = "clk"
clock_name = "core_clock"

# Create the clock signal on the specified input port
design.evalTclString("create_clock -period %s [get_ports %s] -name %s" % (clock_period_ps, port_name, clock_name))
# Propagate the clock signal throughout the design
design.evalTclString("set_propagated_clock [get_clocks {%s}]" % clock_name)

# --- Floorplan ---
# Initialize floorplan object
floorplan = design.getFloorplan()

# Set the die area (bounding box of the chip)
# Bottom-left at (0,0), top-right at (70,70) um
die_area = odb.Rect(design.micronToDBU(0), design.micronToDBU(0),
                    design.micronToDBU(70), design.micronToDBU(70))

# Set the core area (region where standard cells are placed)
# Bottom-left at (6,6), top-right at (64,64) um
core_area = odb.Rect(design.micronToDBU(6), design.micronToDBU(6),
                     design.micronToDBU(64), design.micronToDBU(64))

# Find the standard cell site definition from the technology library
# Replace "stdcell" with the actual site name from your LEF file
site = floorplan.findSite("stdcell") # <<< REPLACE "stdcell" WITH YOUR SITE NAME

# Initialize the floorplan with the defined areas and site
if site:
    floorplan.initFloorplan(die_area, core_area, site)
else:
    print("Error: Site 'stdcell' not found. Floorplan initialization may fail or use default site.")
    # Attempt to initialize anyway, may use a default site or fail depending on OpenROAD version/config
    floorplan.initFloorplan(die_area, core_area)

# Make placement tracks based on the site definition for standard cells
floorplan.makeTracks()

# --- Macro Placement ---
# Get macro instances in the design
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    # Get macro placer object
    mpl = design.getMacroPlacer()
    block = design.getBlock()

    # Define the fence region for macro placement (32,32) to (55,60) um
    fence_lx_um = 32.0
    fence_ly_um = 32.0
    fence_ux_um = 55.0
    fence_uy_um = 60.0

    # Define the halo region around each macro (5 um)
    macro_halo_um = 5.0

    # Define the minimum distance between macros (5 um)
    min_macro_dist_um = 5.0

    # Run macro placement
    mpl.place(
        num_threads = 64, # Number of threads to use
        max_num_macro = len(macros), # Place all macros
        min_num_macro = 0,
        max_num_inst = 0,
        min_num_inst = 0,
        tolerance = 0.1,
        max_num_level = 2,
        coarsening_ratio = 10.0,
        large_net_threshold = 50,
        signature_net_threshold = 50,
        halo_width = macro_halo_um,
        halo_height = macro_halo_um,
        fence_lx = fence_lx_um,
        fence_ly = fence_ly_um,
        fence_ux = fence_ux_um,
        fence_uy = fence_uy_um,
        min_macro_macro_distance = min_macro_dist_um, # Set minimum distance
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
        snap_layer = 0, # No specific snap layer requested
        bus_planning_flag = False,
        report_directory = ""
    )

# --- Standard Cell Placement (Global and Detailed) ---
# Configure and run global placement
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Timing driven mode off for now
gpl.setRoutabilityDrivenMode(True) # Routability driven mode on
gpl.setUniformTargetDensityMode(True)
# No specific iteration count for global placement requested in this prompt
gpl.doInitialPlace(threads = 4)
gpl.doNesterovPlace(threads = 4)
gpl.reset()

# Run initial detailed placement
# Get the site definition (required for displacement conversion)
site = design.getBlock().getRows()[0].getSite()
# Define maximum allowed displacement for detailed placement
max_disp_x_um = 1.0
max_disp_y_um = 3.0
# Convert maximum displacement to site units (required by the API example)
max_disp_x_site_units = int(design.micronToDBU(max_disp_x_um) / site.getWidth())
max_disp_y_site_units = int(design.micronToDBU(max_disp_y_um) / site.getHeight())

# Remove any temporary filler cells before detailed placement
design.getOpendp().removeFillers()
# Perform detailed placement
design.getOpendp().detailedPlacement(max_disp_x_site_units, max_disp_y_site_units, "", False)


# --- Clock Tree Synthesis (CTS) ---
# Set RC values for clock and signal wires
wire_resistance_unit = 0.03574
wire_capacitance_unit = 0.07516
design.evalTclString("set_wire_rc -clock -resistance %s -capacitance %s" % (wire_resistance_unit, wire_capacitance_unit))
design.evalTclString("set_wire_rc -signal -resistance %s -capacitance %s" % (wire_resistance_unit, wire_capacitance_unit))

# Configure and run clock tree synthesis
cts = design.getTritonCts()
# Set the list of available clock buffer cells
cts.setBufferList("BUF_X2")
# Set the root buffer cell
cts.setRootBuffer("BUF_X2")
# Set the sink buffer cell
cts.setSinkBuffer("BUF_X2")
# Set the target clock net for synthesis
cts.setClockNets(clock_name)
# Run CTS
cts.runTritonCts()


# --- Power Delivery Network (PDN) Generation ---
pdngen = design.getPdnGen()

# Find or create Power (VDD) and Ground (VSS) nets
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")

if VDD_net is None:
    VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
    VDD_net.setSigType("POWER")
if VSS_net is None:
    VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
    VSS_net.setSigType("GROUND")

# Mark power/ground nets as special nets
VDD_net.setSpecial()
VSS_net.setSpecial()

# Connect standard cell power/ground pins to the global VDD/VSS nets
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
# Apply the global connections
design.getBlock().globalConnect()

# Set the core power domain with primary power and ground nets
pdngen.setCoreDomain(power = VDD_net, switched_power = None, ground = VSS_net, secondary = [])

# Get required technology layers
tech = design.getTech().getDB().getTech()
m1 = tech.findLayer("metal1")
m4 = tech.findLayer("metal4")
m5 = tech.findLayer("metal5")
m6 = tech.findLayer("metal6")
m7 = tech.findLayer("metal7")
m8 = tech.findLayer("metal8")

# Check if all required layers were found
if not all([m1, m4, m5, m6, m7, m8]):
     print("Error: One or more required metal layers (metal1, metal4, metal5, metal6, metal7, metal8) not found. PDN generation may fail.")

# Set via cut pitch to 0 um for all connections
pdn_cut_pitch_dbu = design.micronToDBU(0)
pdn_cut_pitch = [pdn_cut_pitch_dbu, pdn_cut_pitch_dbu] # [cut_pitch_x, cut_pitch_y]

# Define the core grid name
core_grid_name = "core_grid"
domains = [pdngen.findDomain("Core")]

# Create the main core grid structure
for domain in domains:
    pdngen.makeCoreGrid(domain = domain,
        name = core_grid_name,
        starts_with = pdn.GROUND, # Start with GROUND (often VSS rail on M1)
        pin_layers = [],
        generate_obstructions = [],
        powercell = None,
        powercontrol = None,
        powercontrolnetwork = "STAR") # STAR, RING, or STRIPE pattern

# Get the core grid object
core_grid = pdngen.findGrid(core_grid_name)

# Add standard cell power grid straps and connects to the core grid
if core_grid and m1 and m4 and m7:
    for g in core_grid:
        # M1 followpin stripes for standard cell rail connections (0.07 um width)
        pdngen.makeFollowpin(grid = g,
                             layer = m1,
                             width = design.micronToDBU(0.07),
                             extend = pdn.CORE) # Extend across the core area

        # M4 strap for standard cells (1.2 um width, 1.2 um spacing, 6 um pitch, 0 offset)
        pdngen.makeStrap(grid = g,
                         layer = m4,
                         width = design.micronToDBU(1.2),
                         spacing = design.micronToDBU(1.2),
                         pitch = design.micronToDBU(6),
                         offset = design.micronToDBU(0), # 0 offset
                         number_of_straps = 0, # Auto-calculate number of straps
                         snap = False,
                         starts_with = pdn.GRID, # Relative to grid start
                         extend = pdn.CORE,
                         nets = []) # Apply to all nets in grid

        # M7 strap for standard cells (1.4 um width, 1.4 um spacing, 10.8 um pitch, 0 offset)
        pdngen.makeStrap(grid = g,
                         layer = m7,
                         width = design.micronToDBU(1.4),
                         spacing = design.micronToDBU(1.4),
                         pitch = design.micronToDBU(10.8),
                         offset = design.micronToDBU(0), # 0 offset
                         number_of_straps = 0, # Auto-calculate
                         snap = False,
                         starts_with = pdn.GRID, # Relative to grid start
                         extend = pdn.CORE,
                         nets = [])

        # Via Connections for Standard Cell Grid
        # Connect M1 to M4
        pdngen.makeConnect(grid = g, layer0 = m1, layer1 = m4,
                           cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1], # 0 um via pitch
                           vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
        # Connect M4 to M7
        pdngen.makeConnect(grid = g, layer0 = m4, layer1 = m7,
                           cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1], # 0 um via pitch
                           vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")

# Add core power rings on M7 and M8
# The makeRing API creates a ring using two layers (layer0 and layer1).
# Assuming M7/M8 are used for the ring structure itself.
if core_grid and m7 and m8:
     for g in core_grid:
        # Create ring using M7 and M8 (2 um width, 2 um spacing for both layers, 0 offset)
        pdngen.makeRing(grid = g,
                        layer0 = m7, width0 = design.micronToDBU(2), spacing0 = design.micronToDBU(2),
                        layer1 = m8, width1 = design.micronToDBU(2), spacing1 = design.micronToDBU(2),
                        starts_with = pdn.POWER, # Determine based on which rail is typically outer
                        offset = [design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0)], # Offset (left, bottom, right, top) 0 um
                        pad_offset = [design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0)], # Pad offset 0 um
                        extend = pdn.BOUNDARY, # Extend ring to the boundary of the grid (core area)
                        pad_pin_layers = [], # No specific pad connection layers mentioned
                        nets = []) # Apply to all nets in grid

# Macro specific PDN (Grids and Rings on M5/M6)
if len(macros) > 0 and m5 and m6:
    # Define the halo region around macros for PDN generation (5 um)
    macro_pdn_halo_dbu = design.micronToDBU(5.0)
    macro_pdn_halo = [macro_pdn_halo_dbu, macro_pdn_halo_dbu, macro_pdn_halo_dbu, macro_pdn_halo_dbu] # left, bottom, right, top

    for i, macro_inst in enumerate(macros):
        macro_grid_name = f"macro_grid_{i}"
        for domain in domains:
            # Create a separate grid structure specifically for this macro instance
            pdngen.makeInstanceGrid(domain = domain,
                                    name = macro_grid_name,
                                    starts_with = pdn.GROUND, # Start with GROUND (determine based on macro pins)
                                    inst = macro_inst,
                                    halo = macro_pdn_halo, # Apply halo
                                    pg_pins_to_boundary = True, # Connect macro PG pins to this grid boundary
                                    default_grid = False, # This is not the default core grid
                                    generate_obstructions = [],
                                    is_bump = False)

        # Get the macro-specific grid object
        macro_grid = pdngen.findGrid(macro_grid_name)
        if macro_grid:
             for g in macro_grid:
                # Macro Power Grid Straps on M5 and M6 (1.2 um width, 1.2 um spacing, 6 um pitch, 0 offset)
                pdngen.makeStrap(grid = g, layer = m5,
                                 width = design.micronToDBU(1.2), spacing = design.micronToDBU(1.2), pitch = design.micronToDBU(6),
                                 offset = design.micronToDBU(0), number_of_straps = 0, snap = True, # Snap to grid
                                 starts_with = pdn.GRID, extend = pdn.CORE, nets = [])

                pdngen.makeStrap(grid = g, layer = m6,
                                 width = design.micronToDBU(1.2), spacing = design.micronToDBU(1.2), pitch = design.micronToDBU(6),
                                 offset = design.micronToDBU(0), number_of_straps = 0, snap = True,
                                 starts_with = pdn.GRID, extend = pdn.CORE, nets = [])

                # Via Connections within Macro Grid
                # Connect M5 to M6
                pdngen.makeConnect(grid = g, layer0 = m5, layer1 = m6,
                                   cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1], # 0 um via pitch
                                   vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")

                # Connections between Macro Grid layers and Core Grid layers
                # Connect M4 (core grid) to M5 (macro grid)
                if m4:
                     pdngen.makeConnect(grid = g, layer0 = m4, layer1 = m5,
                                        cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1], # 0 um via pitch
                                        vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
                # Connect M6 (macro grid) to M7 (core grid)
                if m7:
                     pdngen.makeConnect(grid = g, layer0 = m6, layer1 = m7,
                                        cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1], # 0 um via pitch
                                        vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")

                # Macro Power Rings on M5 and M6 (1.5 um width, 1.5 um spacing for both layers, 0 offset)
                if m5 and m6:
                    pdngen.makeRing(grid = g,
                                    layer0 = m5, width0 = design.micronToDBU(1.5), spacing0 = design.micronToDBU(1.5),
                                    layer1 = m6, width1 = design.micronToDBU(1.5), spacing1 = design.micronToDBU(1.5),
                                    starts_with = pdn.POWER, # Determine based on macro pins
                                    offset = [design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0)], # Offset 0 um
                                    pad_offset = [design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0)], # Pad offset 0 um
                                    extend = pdn.CORE, # Extend within the macro grid's core boundary
                                    pad_pin_layers = [],
                                    nets = [])

# Generate the final power delivery network shapes
pdngen.checkSetup() # Verify the PDN configuration
pdngen.buildGrids(False) # Build the grid structures
pdngen.writeToDb(True) # Write the generated power grid shapes to the design database
pdngen.resetShapes() # Clear temporary shapes

# --- IR Drop Analysis ---
# Run IR drop analysis on the Metal1 nodes of the power grids
irdrop = design.getIRDrop()
try:
    # Use TCL command to specify analysis layer
    print("\n--- Running IR Drop Analysis on M1 nodes ---")
    design.evalTclString("analyze_irdrop -power_net VDD -layer metal1")
    design.evalTclString("analyze_irdrop -power_net VSS -layer metal1")
    print("IR Drop analysis completed.")
except Exception as e:
    print(f"Could not perform IR Drop analysis on M1: {e}")
    print("Skipping IR Drop analysis.")

# --- Power Analysis ---
# Report switching, leakage, internal, and total power
# Assumes required timing libraries and activity files are loaded.
power_analyzer = design.getPower()
try:
    print("\n--- Power Analysis Report ---")
    power_analyzer.reportPower()
    print("-----------------------------")
except Exception as e:
    print(f"Could not perform Power Analysis: {e}")
    print("Skipping Power Analysis. Ensure timing libraries and activity files are loaded.")


# --- Routing (Global and Detailed) ---
# Configure and run global routing
grt = design.getGlobalRouter()
# Get routing layers for global routing (M1 to M7)
min_routing_layer = m1.getRoutingLevel() if m1 else 1 # Default to level 1 if layer not found
max_routing_layer = m7.getRoutingLevel() if m7 else 7 # Default to level 7 if layer not found

grt.setMinRoutingLayer(min_routing_layer)
grt.setMaxRoutingLayer(max_routing_layer)
# Set clock routing layers (M1 to M7)
grt.setMinLayerForClock(min_routing_layer)
grt.setMaxLayerForClock(max_routing_layer)

grt.setAdjustment(0.5) # Congestion adjustment factor
grt.setVerbose(True)
# Run global routing. User specified 10 iterations. The API doesn't take this directly.
# The `True` flag often enables iterative routing attempts internally.
grt.globalRoute(True)


# Configure and run detailed routing
drter = design.getTritonRoute()
params = drt.ParamStruct()
# Set bottom and top routing layers for detailed router (M1 to M7)
params.bottomRoutingLayer = m1.getName() if m1 else "metal1"
params.topRoutingLayer = m7.getName() if m7 else "metal7"

# Set other detailed routing parameters
params.outputMazeFile = ""
params.outputDrcFile = ""
params.outputCmapFile = ""
params.outputGuideCoverageFile = ""
params.dbProcessNode = ""
params.enableViaGen = True # Enable via generation
params.drouteEndIter = 1 # Number of detailed routing iterations
params.viaInPinBottomLayer = ""
params.viaInPinTopLayer = ""
params.orSeed = -1
params.orK = 0
params.verbose = 1
params.cleanPatches = True # Clean up routing patches
params.doPa = True # Perform post-route repair
params.singleStepDR = False
params.minAccessPoints = 1
params.saveGuideUpdates = False

# Set detailed routing parameters and run
drter.setParams(params)
drter.main() # Run detailed routing


# --- Output ---
# Write the final design in DEF format
output_def_file = "final.def"
design.writeDef(output_def_file)
print(f"\nFinal DEF saved to {output_def_file}")

# Optional: Write out the routed Verilog netlist (for LVS)
# design.evalTclString("write_verilog final.v")