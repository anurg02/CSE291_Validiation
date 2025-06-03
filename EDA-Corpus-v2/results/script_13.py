import odb
import pdn
import drt
import openroad as ord
import math

# Assumes design and tech are loaded in the OpenROAD environment
# Example: design.readLef("..."), design.readVerilog("...")

# 1. Set up the clock
clock_period_ns = 20
clock_period_ps = clock_period_ns * 1000
clock_port_name = "clk"
clock_name = "core_clock"

# Create clock signal on the specified port
# API 7: openroad.Design.evalTclString(“create_clock -period 50 [get_ports clk_i] -name core_clock”)
print(f"Creating clock '{clock_name}' on port '{clock_port_name}' with period {clock_period_ns} ns...")
design.evalTclString(f"create_clock -period {clock_period_ps} [get_ports {clock_port_name}] -name {clock_name}")

# Propagate the clock signal (needed for timing setup, can be done again after CTS)
# API 8: openroad.Design.evalTclString("set_propagated_clock [core_clock]")
print(f"Propagating clock '{clock_name}'...")
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")


# 2. Perform floorplanning
# Code Piece 4: Template of running floorplanning
print("Performing floorplanning...")
floorplan = design.getFloorplan()
block = design.getBlock()
tech = design.getTech().getDB().getTech()

# Get a site from the design's rows
rows = block.getRows()
if not rows:
    print("Error: No rows found in the design. Cannot perform floorplanning.")
    exit()
site = rows[0].getSite()
if site is None:
    print("Error: Site not found in the design's rows. Cannot perform floorplanning.")
    exit()

# Calculate required core area based on target utilization
target_utilization = 0.45
total_std_cell_area = 0
for inst in block.getInsts():
    # Assuming instances that are not blocks are standard cells
    if not inst.getMaster().isBlock():
        bbox = inst.getBBox()
        total_std_cell_area += bbox.getArea()

if total_std_cell_area <= 0:
    print("Warning: Total standard cell area is zero. Cannot calculate core area based on utilization.")
    print("Using original core area bounds for floorplan initialization.")
    # Fallback to using original core bounds if no std cells
    original_core = block.getCoreArea()
    core_width_dbu = original_core.getWidth()
    core_height_dbu = original_core.getHeight()
else:
    # Required area in DBU^2 based on utilization
    required_core_area_dbu2 = int(total_std_cell_area / target_utilization)

    # Determine core dimensions (width/height) respecting site size
    # Aim for dimensions that give at least the required area
    # Simple approach: Start with a square side length based on required area,
    # then align to site dimensions.
    min_core_dim_dbu = int(math.sqrt(required_core_area_dbu2))
    site_width_dbu = site.getWidth()
    site_height_dbu = site.getHeight()

    # Calculate core dimensions by rounding up to the nearest site grid
    # Ensure width*height is at least the required area
    core_width_dbu = (min_core_dim_dbu + site_width_dbu - 1) // site_width_dbu * site_width_dbu
    core_height_dbu = (min_core_dim_dbu + site_height_dbu - 1) // site_height_dbu * site_height_dbu

    # Adjust dimensions if the initial rounding results in an area too small
    while core_width_dbu * core_height_dbu < required_core_area_dbu2:
         # Simple adjustment: increment width by site_width until area is sufficient
         # A more sophisticated approach would balance dimensions
         core_width_dbu += site_width_dbu


# Set core margin
core_margin_micron = 5
core_margin_dbu = design.micronToDBU(core_margin_micron)

# Define core and die areas
# Place core origin at the margin (5um from die origin)
core_area = odb.Rect(core_margin_dbu, core_margin_dbu,
                     core_margin_dbu + core_width_dbu, core_margin_dbu + core_height_dbu)

# Die area is core area plus margin on all sides
die_area = odb.Rect(0, 0,
                    core_area.xMax() + core_margin_dbu, core_area.yMax() + core_margin_dbu)

# Initialize floorplan with calculated die and core areas
floorplan.initFloorplan(die_area, core_area, site)
# Make tracks necessary for standard cell placement based on site information
floorplan.makeTracks()


# 3. Place I/O pins
# Code Piece 5: Template of placing I/O pins
print("Placing I/O pins...")
io_placer = design.getIOPlacer()
# Parameters can be tuned here if needed, e.g., setRandSeed
# params = io_placer.getParameters()

# Set I/O pin layers for horizontal and vertical connections
metal8 = tech.findLayer("metal8")
metal9 = tech.findLayer("metal9")

if metal8 is None:
    print("Warning: metal8 layer not found. Cannot add horizontal IO layers.")
else:
    # Add metal8 for horizontal pins
    io_placer.addHorLayer(metal8)

if metal9 is None:
    print("Warning: metal9 layer not found. Cannot add vertical IO layers.")
else:
    # Add metal9 for vertical pins
    io_placer.addVerLayer(metal9)

# Run I/O placement algorithm (e.g., using annealing)
io_placer.runAnnealing(True) # True for random mode


# 4. Place macros and standard cells
print("Performing placement (macro and standard cell)...")
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

# Macro placement
if len(macros) > 0:
    print(f"Placing {len(macros)} macros...")
    mpl = design.getMacroPlacer()
    core = block.getCoreArea()

    # Set halo region around each macro (requested 5 um)
    macro_halo_micron = 5
    # Note: mpl.place halo parameters are in microns

    # Min distance between macros (requested 5 um) is not a direct parameter.
    # Setting a halo for placement helps create clearance.
    # The placement algorithm and legalization prevent overlaps.
    mpl.place(
        num_threads = 64, # Use a reasonable number of threads
        max_num_macro = len(macros), # Specify max number of macros to place (place all)
        halo_width = macro_halo_micron, # Macro halo width in microns
        halo_height = macro_halo_micron, # Macro halo height in microns
        # Specify placement region (core area)
        fence_lx = block.dbuToMicrons(core.xMin()),
        fence_ly = block.dbuToMicrons(core.yMin()),
        fence_ux = block.dbuToMicrons(core.xMax()),
        fence_uy = block.dbuToMicrons(core.yMax()),
        # Other parameters from Example 1 or defaults can be used
        min_num_macro = 0,
        max_num_inst = 0, # Do not place standard cells with this macro placer
        min_num_inst = 0,
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
        target_util = target_utilization, # Use calculated target utilization
        target_dead_space = 0.05,
        min_ar = 0.33,
        # snap_layer = 4, # Can optionally snap macro pins to a layer's grid
        bus_planning_flag = False,
        report_directory = ""
    )


# Standard cell placement (Global)
print("Performing global placement for standard cells...")
gpl = design.getReplace()
# Basic global placement setup (can be tuned)
gpl.setTimingDrivenMode(False) # Set to True if timing analysis is ready
gpl.setRoutabilityDrivenMode(True)
gpl.setUniformTargetDensityMode(True)
# Example 1 used setInitialPlaceMaxIter(10), using default here
gpl.doInitialPlace(threads = 4)
gpl.doNesterovPlace(threads = 4)
gpl.reset() # Reset placer state


# Standard cell placement (Detailed)
print("Performing detailed placement...")
opendp = design.getOpendp()
# Remove potential existing fillers before detailed placement
opendp.removeFillers()

# Set maximum displacement for detailed placement
max_disp_x_micron = 1
max_disp_y_micron = 3
max_disp_x_dbu = design.micronToDBU(max_disp_x_micron)
max_disp_y_dbu = design.micronToDBU(max_disp_y_micron)

# Detailed placement displacement is typically in site units based on OpenDB/OpenDP
# Example 1 scales DBU by site width/height
site_width_dbu = site.getWidth()
site_height_dbu = site.getHeight()
max_disp_x_site_units = int(max_disp_x_dbu / site_width_dbu)
max_disp_y_site_units = int(max_disp_y_dbu / site_height_dbu)

# Perform detailed placement
# API 1 in Example 1: design.getOpendp().detailedPlacement(max_disp_x, max_disp_y, "", False)
opendp.detailedPlacement(max_disp_x_site_units, max_disp_y_site_units, "", False)


# 5. Dump DEF after placement
print("Writing DEF after placement...")
design.writeDef("placement.def")


# 6. Perform Clock Tree Synthesis (CTS)
print("Performing CTS...")
# Code Piece 1: Template of running CTS

# Set RC values for clock and signal nets
# API 1: openroad.Design.evalTclString("set_wire_rc -clock -resistance 0.03574 -capacitance 0.07516")
wire_resistance = 0.03574
wire_capacitance = 0.07516
design.evalTclString(f"set_wire_rc -clock -resistance {wire_resistance} -capacitance {wire_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {wire_resistance} -capacitance {wire_capacitance}")

cts = design.getTritonCts() # API 5
# Get CTS parameters object
parms = cts.getParms()
# Set wire segment unit (e.g., 20 DBU or 20um converted to DBU)
# Example 1 uses 20, let's assume 20 DBU
parms.setWireSegmentUnit(20) # Use 20 DBU as per Example 1 code, not micron conversion

# Configure clock buffers
cts_buffer_cell = "BUF_X2"
# API 17: Set available clock buffer library cells
cts.setBufferList(cts_buffer_cell)
# API 13: Set the rooting clock buffer
cts.setRootBuffer(cts_buffer_cell)
# API 9: Set the sinking clock buffer
cts.setSinkBuffer(cts_buffer_cell)

# Run CTS
cts.runTritonCts() # API 4

# Propagate the clock signal again after CTS to update timing
# API 8: openroad.Design.evalTclString("set_propagated_clock [core_clock]")
print(f"Propagating clock '{clock_name}' again after CTS...")
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")


# 7. Dump DEF after CTS
print("Writing DEF after CTS...")
design.writeDef("cts.def")


# 8. Construct Power Delivery Network (PDN)
print("Constructing PDN...")
# Example 1 and Code Piece 3 provide templates for PDN generation

pdngen = design.getPdnGen()

# Set up global power/ground connections if not already done (safer to repeat)
# Example 1: Find or create VDD/VSS nets and set special flag
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

# Create VDD/VSS nets if they don't exist and set properties
if VDD_net is None:
    VDD_net = odb.dbNet_create(block, "VDD")
    # API 12: odb.dbNet.setSigType(str(type))
    VDD_net.setSigType("POWER")
    print("Created VDD net.")
if VDD_net is not None:
    VDD_net.setSpecial() # Mark as special net

if VSS_net is None:
    VSS_net = odb.dbNet_create(block, "VSS")
    # API 12: odb.dbNet.setSigType(str(type))
    VSS_net.setSigType("GROUND")
    print("Created VSS net.")
if VSS_net is not None:
    VSS_net.setSpecial() # Mark as special net

# Set the core power domain with the found/created nets
# API 11: pdn.PdnGen.setCoreDomain(...)
if VDD_net is not None and VSS_net is not None:
    print("Setting core power domain...")
    pdngen.setCoreDomain(power = VDD_net,
                         switched_power = None, # Assuming no switched power
                         ground = VSS_net,
                         secondary = list()) # Assuming no secondary power nets
else:
    print("Warning: VDD or VSS net not available. Cannot set core power domain.")


# Define metal layers for PDN
metal1 = tech.findLayer("metal1")
metal4 = tech.findLayer("metal4")
metal5 = tech.findLayer("metal5")
metal6 = tech.findLayer("metal6")
metal7 = tech.findLayer("metal7")
metal8 = tech.findLayer("metal8")

if metal1 is None or metal4 is None or metal7 is None or metal8 is None:
    print("Error: Required metal layers (metal1, metal4, metal7, metal8) not found. Cannot build core PDN.")
    # exit() # Don't exit, allow macro PDN if layers exist
    can_build_core_pdn = False
else:
    can_build_core_pdn = True

if (metal5 is None or metal6 is None) and len(macros) > 0:
     print("Warning: Required metal layers (metal5, metal6) not found for macro PDN.")
     can_build_macro_pdn = False
else:
     can_build_macro_pdn = True # Check needs to include len(macros)

if not can_build_core_pdn and (not can_build_macro_pdn or len(macros) == 0):
     print("Error: Cannot build any PDN grids due to missing layers or no macros.")


if can_build_core_pdn or (can_build_macro_pdn and len(macros) > 0):
    # Define halo for macro instance grids (requested 5 um) in DBU
    macro_halo_pdn_micron = 5
    macro_halo_pdn_dbu = design.micronToDBU(macro_halo_pdn_micron)
    halo_rect_dbu = [macro_halo_pdn_dbu] * 4 # [left, bottom, right, top]

    # Via cut pitch set to 0 um (in DBU)
    via_cut_pitch_micron = 0
    via_cut_pitch_dbu = design.micronToDBU(via_cut_pitch_micron)
    pdn_cut_pitch = [via_cut_pitch_dbu, via_cut_pitch_dbu] # [x_pitch, y_pitch]

    core_domain = pdngen.findDomain("Core")
    if core_domain is None:
        print("Error: Core domain not found for PDN creation.")
    else:
        # Create the main core grid structure (for standard cells and rings)
        # Example 1: pdngen.makeCoreGrid(...)
        print("Creating main core grid...")
        pdngen.makeCoreGrid(domain = core_domain,
                            name = "main_core_grid", # A name for the main grid
                            starts_with = pdn.GROUND, # Start pattern with ground net connection
                            pin_layers = [], # Layers to connect to pins (usually done by followpin)
                            generate_obstructions = [],
                            powercell = None,
                            powercontrol = None,
                            powercontrolnetwork = "STAR")

        # Get the main grid object by name
        main_grid = pdngen.findGrid("main_core_grid")
        if main_grid is None:
             print("Error: Main grid 'main_core_grid' not found after creation!")
        else:
            # Add stripes to the main grid for standard cells
            # Followpin on M1 for standard cell rails
            if metal1 is not None:
                print("Adding M1 followpin stripes...")
                m1_width_micron = 0.07
                # API 10: pdn.PdnGen.makeFollowpin(...)
                pdngen.makeFollowpin(grid = main_grid,
                                     layer = metal1,
                                     width = design.micronToDBU(m1_width_micron),
                                     extend = pdn.CORE) # Extend within core area

            # Straps on M4 for standard cells
            if metal4 is not None:
                print("Adding M4 standard cell straps...")
                m4_width_micron = 1.2
                m4_spacing_micron = 1.2
                m4_pitch_micron = 6
                m4_offset_micron = 0
                # API 14: pdn.PdnGen.makeStrap(...)
                pdngen.makeStrap(grid = main_grid,
                                 layer = metal4,
                                 width = design.micronToDBU(m4_width_micron),
                                 spacing = design.micronToDBU(m4_spacing_micron),
                                 pitch = design.micronToDBU(m4_pitch_micron),
                                 offset = design.micronToDBU(m4_offset_micron),
                                 number_of_straps = 0, # Auto-calculate
                                 snap = False, # Don't necessarily snap to layer grid
                                 starts_with = pdn.GRID, # Start pattern from grid boundary
                                 extend = pdn.CORE, # Extend within core area
                                 nets = []) # Apply to all nets in the grid (VDD/VSS)

            # Straps on M7 for standard cells
            if metal7 is not None:
                print("Adding M7 standard cell straps...")
                m7_width_micron = 1.4
                m7_spacing_micron = 1.4
                m7_pitch_micron = 10.8
                m7_offset_micron = 0
                # API 14: pdn.PdnGen.makeStrap(...)
                pdngen.makeStrap(grid = main_grid,
                                 layer = metal7,
                                 width = design.micronToDBU(m7_width_micron),
                                 spacing = design.micronToDBU(m7_spacing_micron),
                                 pitch = design.micronToDBU(m7_pitch_micron),
                                 offset = design.micronToDBU(m7_offset_micron),
                                 number_of_straps = 0, # Auto-calculate
                                 snap = False, # Don't necessarily snap to layer grid
                                 starts_with = pdn.GRID,
                                 extend = pdn.CORE,
                                 nets = [])


            # Power Rings on M7 and M8
            if metal7 is not None and metal8 is not None:
                print("Adding M7/M8 power rings...")
                ring_width_micron = 2
                ring_spacing_micron = 2
                ring_offset_micron = 0 # Use 0 offset as requested
                ring_offset_dbu = design.micronToDBU(ring_offset_micron)
                # API 6: pdn.PdnGen.makeRing(...)
                pdngen.makeRing(grid = main_grid,
                                layer0 = metal7, # First layer for the ring
                                width0 = design.micronToDBU(ring_width_micron),
                                spacing0 = design.micronToDBU(ring_spacing_micron),
                                layer1 = metal8, # Second layer for the ring
                                width1 = design.micronToDBU(ring_width_micron), # Same width/spacing as M7
                                spacing1 = design.micronToDBU(ring_spacing_micron), # Same width/spacing as M7
                                starts_with = pdn.GRID, # Start pattern from grid boundary
                                offset = [ring_offset_dbu]*4, # Offset [left, bottom, right, top]
                                pad_offset = [0]*4, # No pad offset specified
                                extend = True, # Extend the ring around the defined grid boundary
                                pad_pin_layers = [], # No pad pin layers specified
                                nets = []) # Applied to all nets in the grid (VDD/VSS)

            # Add Via Connections between standard cell grid layers
            # API 15: pdn.PdnGen.makeConnect(...)
            # Use 0 cut pitch as requested
            if metal1 is not None and metal4 is not None:
                print("Adding M1-M4 vias...")
                pdngen.makeConnect(grid = main_grid, layer0 = metal1, layer1 = metal4,
                                   cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])

            if metal4 is not None and metal7 is not None:
                print("Adding M4-M7 vias...")
                pdngen.makeConnect(grid = main_grid, layer0 = metal4, layer1 = metal7,
                                   cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])

            if metal7 is not None and metal8 is not None:
                 # Connect M7 straps/rings to M8 rings
                print("Adding M7-M8 vias...")
                pdngen.makeConnect(grid = main_grid, layer0 = metal7, layer1 = metal8,
                                   cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])


    # Create power grid for macro blocks (if any)
    # Code Piece 3: Template for macro PDN
    if len(macros) > 0 and can_build_macro_pdn:
        print(f"Creating PDN grids for {len(macros)} macros...")
        m5_width_micron = 1.2
        m5_spacing_micron = 1.2
        m5_pitch_micron = 6
        m5_offset_micron = 0

        m6_width_micron = 1.2
        m6_spacing_micron = 1.2
        m6_pitch_micron = 6
        m6_offset_micron = 0

        m5_offset_dbu = design.micronToDBU(m5_offset_micron)
        m6_offset_dbu = design.micronToDBU(m6_offset_micron)


        for i, macro_inst in enumerate(macros):
            macro_grid_name = f"macro_grid_{i}"
            # Create separate instance grid for each macro
            # Example 1/Code Piece 3: pdngen.makeInstanceGrid(...)
            pdngen.makeInstanceGrid(domain = core_domain,
                                    name = macro_grid_name,
                                    starts_with = pdn.GROUND, # Start pattern with ground connection
                                    inst = macro_inst, # Associate grid with this instance
                                    halo = halo_rect_dbu, # Apply macro halo around this instance
                                    pg_pins_to_boundary = True, # Connect macro PG pins to grid boundary
                                    default_grid = False, # This is not the default grid
                                    generate_obstructions = [],
                                    is_bump = False)

            macro_grid = pdngen.findGrid(macro_grid_name)
            if macro_grid is None:
                print(f"Error: Macro grid '{macro_grid_name}' not found after creation!")
                continue

            # Add straps on M5 for macros
            if metal5 is not None:
                print(f"Adding M5 straps for macro {macro_inst.getName()}...")
                # API 14: pdn.PdnGen.makeStrap(...)
                pdngen.makeStrap(grid = macro_grid,
                                 layer = metal5,
                                 width = design.micronToDBU(m5_width_micron),
                                 spacing = design.micronToDBU(m5_spacing_micron),
                                 pitch = design.micronToDBU(m5_pitch_micron),
                                 offset = m5_offset_dbu,
                                 number_of_straps = 0, # Auto-calculate
                                 snap = True, # Snap to grid (macro grid)
                                 starts_with = pdn.GRID,
                                 extend = pdn.CORE, # Extend within macro's core boundary
                                 nets = []) # Apply to all nets in the grid (VDD/VSS)

            # Add straps on M6 for macros
            if metal6 is not None:
                print(f"Adding M6 straps for macro {macro_inst.getName()}...")
                # API 14: pdn.PdnGen.makeStrap(...)
                pdngen.makeStrap(grid = macro_grid,
                                 layer = metal6,
                                 width = design.micronToDBU(m6_width_micron),
                                 spacing = design.micronToDBU(m6_spacing_micron),
                                 pitch = design.micronToDBU(m6_pitch_micron),
                                 offset = m6_offset_dbu,
                                 number_of_straps = 0, # Auto-calculate
                                 snap = True, # Snap to grid
                                 starts_with = pdn.GRID,
                                 extend = pdn.CORE, # Extend within macro's core boundary
                                 nets = []) # Apply to all nets in the grid (VDD/VSS)

            # Add Via Connections between macro grid layers and adjacent core grid layers
            # API 15: pdn.PdnGen.makeConnect(...)
            # Use 0 cut pitch as requested
            # M4 (core grid layer, connects to M5 macro grid)
            if metal4 is not None and metal5 is not None:
                print(f"Adding M4-M5 vias for macro {macro_inst.getName()}...")
                pdngen.makeConnect(grid = macro_grid, layer0 = metal4, layer1 = metal5,
                                   cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
            # M5 (macro grid) to M6 (macro grid)
            if metal5 is not None and metal6 is not None:
                print(f"Adding M5-M6 vias for macro {macro_inst.getName()}...")
                pdngen.makeConnect(grid = macro_grid, layer0 = metal5, layer1 = metal6,
                                   cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
            # M6 (macro grid) to M7 (core grid layer)
            if metal6 is not None and metal7 is not None:
                print(f"Adding M6-M7 vias for macro {macro_inst.getName()}...")
                pdngen.makeConnect(grid = macro_grid, layer0 = metal6, layer1 = metal7,
                                   cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])

    # Generate the final power delivery network
    print("Building and writing PDN grids to database...")
    pdngen.checkSetup() # Verify configuration
    pdngen.buildGrids(False) # Build the power grid shapes in memory
    pdngen.writeToDb(True, ) # Write power grid shapes from memory to the design database
    pdngen.resetShapes() # Reset temporary shapes in memory


# 9. Dump DEF after PDN
print("Writing DEF after PDN construction...")
design.writeDef("pdn.def")


# 10. Perform IR drop analysis on M1 nodes
print("Performing IR drop analysis on M1 nodes...")
irdrop = design.getIRdrop()

# Need to set power/ground nets for analysis
if VDD_net is not None:
    irdrop.setPowerNet(VDD_net)
else:
    print("Warning: VDD net not found for IR drop analysis.")
if VSS_net is not None:
    irdrop.setGroundNet(VSS_net)
else:
     print("Warning: VSS net not found for IR drop analysis.")

# Set the layer on which to analyze IR drop nodes (M1 nodes)
if metal1 is not None:
    irdrop.setAnalysisNodeLayer(metal1)
    # Run analysis - requires a valid RC corner (typically loaded with technology)
    try:
        irdrop.analyze()
        print("IR drop analysis completed.")
        # Results can be queried or are part of subsequent reports depending on tool setup
        # E.g., access results using irdrop.getIRdrop(), irdrop.getWorstCaseNets(), etc.
    except Exception as e:
        print(f"Error during IR drop analysis: {e}. Ensure analysis setup is complete (e.g., SPEF loaded, timing initialized).")
else:
    print("Warning: metal1 layer not found. Skipping IR drop analysis.")


# 11. Report power
# This requires a timing setup (corners, SPEF/parasitics) to be accurate
# Assuming a basic power report is requested using a built-in command
print("Reporting power...")
# This Tcl command typically reports total, switching, internal, leakage power
# The accuracy depends heavily on previous steps like timing analysis and parasitics extraction
try:
    # This command might require timing to be fully set up (corners, library delays, parasitics)
    # Use catch to prevent script from stopping if power reporting fails
    power_report_output = design.evalTclString("catch {report_power}")
    print("--- Power Report ---")
    print(power_report_output)
    print("--------------------")
except Exception as e:
    print(f"Error evaluating 'report_power': {e}. Ensure timing and parasitics are properly set up.")


# 12. Perform Routing
print("Performing global routing...")
# Configure and run global routing
grt = design.getGlobalRouter()

# Set routing layer ranges for signal and clock nets (M1 to M7)
if metal1 is not None and metal7 is not None:
    signal_low_layer_level = metal1.getRoutingLevel()
    signal_high_layer_level = metal7.getRoutingLevel()

    # Set minimum and maximum routing layers for signal nets
    grt.setMinRoutingLayer(signal_low_layer_level)
    grt.setMaxRoutingLayer(signal_high_layer_level)

    # Set minimum and maximum routing layers for clock nets (same range)
    # API 2: grt.GlobalRouter.setMinLayerForClock(int(min_layer))
    # API 3: grt.GlobalRouter.setMaxLayerForClock(int(max_layer))
    grt.setMinLayerForClock(signal_low_layer_level)
    grt.setMaxLayerForClock(signal_high_layer_level)

    # Basic global routing settings (can be tuned)
    grt.setAdjustment(0.5) # Congestion adjustment factor
    grt.setVerbose(True)

    # Run global routing (True usually enables timing-driven mode if timing setup is complete)
    grt.globalRoute(True)

    print("Writing DEF after global routing...")
    design.writeDef("grt.def")

    print("Performing detailed routing...")
    # Configure and run detailed routing
    drter = design.getTritonRoute() # API 20
    params = drt.ParamStruct() # Detailed router parameters structure

    # Set routing layers for detailed routing
    params.bottomRoutingLayer = metal1.getName()
    params.topRoutingLayer = metal7.getName()

    # Other parameters from Example 1 detailed routing setup
    params.outputMazeFile = ""
    params.outputDrcFile = "" # Specify a file name to dump DRC violations
    params.outputCmapFile = ""
    params.outputGuideCoverageFile = ""
    params.dbProcessNode = "" # Technology node string, often not strictly needed if tech file is good
    params.enableViaGen = True # Enable via generation
    params.drouteEndIter = 1 # Number of detailed routing iterations (usually 1-3)
    params.viaInPinBottomLayer = "" # Specify if via-in-pin is restricted below a layer
    params.viaInPinTopLayer = "" # Specify if via-in-pin is restricted above a layer
    params.orSeed = -1 # Random seed for optimization (-1 for default)
    params.orK = 0 # Optimization parameter (0 for default)
    params.verbose = 1 # Verbosity level
    params.cleanPatches = True # Clean up routing patches
    params.doPa = True # Perform post-route antenna fixing
    params.singleStepDR = False # Run detailed routing in a single step
    params.minAccessPoints = 1 # Minimum access points for pins
    params.saveGuideUpdates = False # Save guide updates during routing

    # Set the parameters for the detailed router
    drter.setParams(params)
    # Run detailed routing
    drter.main()

    # Insert filler cells after detailed routing to fill gaps
    # This helps prevent DRC issues related to minimum density rules
    print("Inserting filler cells...")
    # Find available filler cell masters (assuming names like "FILLCELL_")
    filler_masters = list()
    filler_cells_prefix = "FILLCELL_" # Common naming convention
    for lib in design.getTech().getDB().getLibs():
        for master in lib.getMasters():
            # Check if master type is CORE_SPACER or if name matches prefix
            if master.getType() == "CORE_SPACER" or master.getName().startswith(filler_cells_prefix):
                 filler_masters.append(master)

    if len(filler_masters) == 0:
        print("Warning: No filler cells found (type CORE_SPACER or name starting with 'FILLCELL_'). Skipping filler placement.")
    else:
        # Perform filler cell placement
        opendp.fillerPlacement(filler_masters = filler_masters,
                               prefix = filler_cells_prefix,
                               verbose = False)


    print("Writing final DEF after detailed routing...")
    # Write the final DEF file containing placement and routing
    design.writeDef("final.def")

else:
    print("Warning: metal1 or metal7 layer not found. Skipping global and detailed routing.")

print("Script finished.")