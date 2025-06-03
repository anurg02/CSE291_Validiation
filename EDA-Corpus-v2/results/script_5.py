import openroad as ord
import odb
import pdn
import drt
import math

# Assume the design object 'design' is already loaded with technology, library, and netlist

# 1. Clock Setup
clock_period_ns = 20
clock_port_name = "clk_i"
clock_name = "core_clock"

# Create clock signal at the specified port with the given period
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")

# Propagate the clock signal
# API 8: Propagate the clock signal
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Set unit resistance and capacitance for clock and signal nets
# API 1: Set the unit resistance value and unit capacitance value of the clock net
design.evalTclString("set_wire_rc -clock -resistance 0.0435 -capacitance 0.0817")
design.evalTclString("set_wire_rc -signal -resistance 0.0435 -capacitance 0.0817")

# 2. Floorplanning
# Set target utilization
target_utilization = 0.50
# Set spacing between core and die boundary in microns
core_die_spacing_um = 14
core_die_spacing_dbu = design.micronToDBU(core_die_spacing_um)

# Calculate total cell area to estimate core size
total_cell_area_dbu = 0
for inst in design.getBlock().getInsts():
    if not inst.getMaster().isBlock(): # Consider only standard cells
        total_cell_area_dbu += inst.getMaster().getWidth() * inst.getMaster().getHeight()

# Estimate required core area based on total cell area and utilization
required_core_area_dbu = total_cell_area_dbu / target_utilization

# Estimate core side length (assuming a square core for simplicity in calculation)
# This is a simplification; a real floorplan might consider aspect ratio
core_side_dbu = int(math.sqrt(required_core_area_dbu))

# Calculate die dimensions based on core size and spacing
die_width_dbu = core_side_dbu + 2 * core_die_spacing_dbu
die_height_dbu = core_side_dbu + 2 * core_die_spacing_dbu

# Define die and core areas
die_area = odb.Rect(0, 0, die_width_dbu, die_height_dbu)
core_area = odb.Rect(core_die_spacing_dbu, core_die_spacing_dbu,
                     core_side_dbu + core_die_spacing_dbu, core_side_dbu + core_die_spacing_dbu)

# Get the first site found in the library
site = None
for lib in design.getTech().getDB().getLibs():
    for s in lib.getSites():
        site = s
        break
    if site:
        break

if not site:
    print("Error: No site found in the library.")
else:
    # Initialize floorplan with calculated areas and site
    # Code Piece 4: Template of running floorplanning with specific die and core area
    floorplan = design.getFloorplan()
    floorplan.initFloorplan(die_area, core_area, site)

    # Make placement tracks
    floorplan.makeTracks()

# 3. Pin Placement
# Configure and run I/O pin placement
# Code Piece 5: Template of placing I/O pins (ports)
io_placer = design.getIOPlacer()
params = io_placer.getParameters()
# Set minimum distance between pins to 0 (as per Example 1 which implies 0 for unmentioned settings)
params.setMinDistance(design.micronToDBU(0))
params.setCornerAvoidance(design.micronToDBU(0)) # No specific corner avoidance mentioned
params.setRandSeed(0) # No specific seed mentioned, use 0 for deterministic? Or omit. Let's omit.
params.setMinDistanceInTracks(False) # Not specified, use False

# Get metal layers for pin placement
m8 = design.getTech().getDB().getTech().findLayer("metal8")
m9 = design.getTech().getDB().getTech().findLayer("metal9")

if m8 and m9:
    # Place I/O pins on metal8 (horizontal) and metal9 (vertical) layers
    io_placer.addHorLayer(m8)
    io_placer.addVerLayer(m9)
    # Run IO placement (using annealing mode, random mode is often used)
    IOPlacer_random_mode = True # Use random mode as in example
    io_placer.runAnnealing(IOPlacer_random_mode)
else:
    print("Warning: Metal layers M8 or M9 not found for pin placement.")


# 4. Placement
# Set halo region around each macro for placement
macro_halo_um = 5
macro_halo_dbu = design.micronToDBU(macro_halo_um)
# Note: The prompt asks to place macros first with min distance, then standard cells.
# OpenROAD's standard flow typically handles macros within global/detailed placement
# after initial floorplan setup. We will set a macro halo which instructs the placer
# to keep standard cells away from macro boundaries. Manual, constrained macro placement
# needs more complex scripting or Tcl commands not directly available in simple API calls.
# We will rely on the placer respecting the macro halo and proceed to global/detailed placement.

# Set macro halo for the global placer
gpl = design.getReplace()
gpl.setMacroHalo(macro_halo_dbu, macro_halo_dbu)

# Run global placement
# No specific iterations mentioned for global placement this time, let it run default
# Example 1 used 10 iterations, but this prompt didn't specify. Let's just run the main function.
gpl.doNesterovPlace()

# Run detailed placement (initial)
# Set max displacement for detailed placement
max_disp_x_um = 0.5
max_disp_y_um = 1.0
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

# Detailed placement typically operates on site units displacement.
site = design.getBlock().getRows()[0].getSite() if design.getBlock().getRows() else None
if site:
    # Convert displacement to site units for detailed placement API
    max_disp_x_site = int(max_disp_x_dbu / site.getWidth())
    max_disp_y_site = int(max_disp_y_dbu / site.getHeight())
    # Remove filler cells if any were inserted prior (not in this script yet)
    # design.getOpendp().removeFillers() # Not needed as fillers aren't inserted yet
    design.getOpendp().detailedPlacement(max_disp_x_site, max_disp_y_site, "", False)
else:
    print("Warning: No sites found to calculate detailed placement displacement in site units.")
    # Fallback to DBU if site is not available (check API, may need site units)
    # Let's assume site is available from floorplan.

# 5. Clock Tree Synthesis (CTS)
# Get the CTS module
# API 5: Get the module to perform CTS
cts = design.getTritonCts()

# Set available clock buffer cell list
buffer_cell = "BUF_X3"
# API 19: Set the available clock buffer library cells with the name
cts.setBufferList(buffer_cell)
# API 13: Set the rooting clock buffer (starting point) with the name
cts.setRootBuffer(buffer_cell)
# API 10: Set the sinking clock buffer (end point) with the name
cts.setSinkBuffer(buffer_cell)

# Set the clock net name for CTS
# API 18: Set the clock net by the name
cts.setClockNets(clock_name)

# Run CTS
# API 4: Run CTS (clock tree synthesis)
cts.runTritonCts()

# After CTS, re-run detailed placement to fix any displacement caused by buffer insertion
if site:
    # The prompt specifies max displacement 0.5um x, 1.0um y for detailed placement.
    # This should apply to the post-CTS detailed placement as well.
    design.getOpendp().detailedPlacement(max_disp_x_site, max_disp_y_site, "", False)


# 6. Power Delivery Network (PDN)
# Import pdn and odb (already done at the top)

# Get PDN generator module
pdngen = design.getPdnGen()

# Define power and ground nets and set signal types
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")

# Create VDD/VSS nets if they don't exist and set signal type
if VDD_net is None:
    VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
    # API 12: Set the signal type of the net
    VDD_net.setSigType("POWER")
if VSS_net is None:
    VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
    VSS_net.setSigType("GROUND")

# Mark power/ground nets as special nets (required for PDN generation)
if VDD_net: VDD_net.setSpecial()
if VSS_net: VSS_net.setSpecial()

# Connect power pins to global nets
# Standard practice is to connect cell power pins (like VDD/VSS) to the global power/ground nets
# Use globalConnect
# Find power and ground pins from standard cells
design.getBlock().addGlobalConnect(region=None, instPattern="*", pinPattern="VDD", net=VDD_net, do_connect=True)
design.getBlock().addGlobalConnect(region=None, instPattern="*", pinPattern="VSS", net=VSS_net, do_connect=True)
# Apply global connections
design.getBlock().globalConnect()


# Set core power domain
# API 9: Set the voltage domain of the design core
pdngen.setCoreDomain(power=VDD_net, switched_power=None, ground=VSS_net, secondary=[])

# Get the core domain grid
domains = [pdngen.findDomain("Core")]
if not domains:
    print("Error: Core domain not found.")
else:
    # Create the main core grid structure
    # starts_with determines which net's strap is placed first at grid boundaries
    pdngen.makeCoreGrid(domain=domains[0],
                        name="core_grid",
                        starts_with=pdn.GROUND, # Common to start with Ground
                        pin_layers=[],
                        generate_obstructions=[],
                        powercell=None,
                        powercontrol=None,
                        powercontrolnetwork="") # Use default network

    # Get metal layers for PDN
    m1 = design.getTech().getDB().getTech().findLayer("metal1")
    m4 = design.getTech().getDB().getTech().findLayer("metal4")
    m5 = design.getTech().getDB().getTech().findLayer("metal5")
    m6 = design.getTech().getDB().getTech().findLayer("metal6")
    m7 = design.getTech().getDB().getTech().findLayer("metal7")
    m8 = design.getTech().getDB().getTech().findLayer("metal8")

    # Via pitch between grids (connecting layers)
    via_pitch_um = 2
    via_pitch_dbu = design.micronToDBU(via_pitch_um)
    pdn_cut_pitch = [via_pitch_dbu, via_pitch_dbu] # Apply to both X and Y

    # Standard cell and core grid configuration
    core_grid = pdngen.findGrid("core_grid")
    if core_grid:
        for g in core_grid: # Iterate through found grids with this name
            # Create horizontal power straps on metal1 following standard cell pins
            m1_width_um = 0.07
            m1_width_dbu = design.micronToDBU(m1_width_um)
            # API 11: Create the PDN stripes at the lowest metal layer and following the pin pattern
            pdngen.makeFollowpin(grid=g,
                                layer=m1,
                                width=m1_width_dbu,
                                extend=pdn.CORE) # Extend within the core area

            # Create power straps on metal4 for standard cells
            m4_width_um = 1.2
            m4_spacing_um = 1.2
            m4_pitch_um = 6
            m4_width_dbu = design.micronToDBU(m4_width_um)
            m4_spacing_dbu = design.micronToDBU(m4_spacing_um)
            m4_pitch_dbu = design.micronToDBU(m4_pitch_um)
            m4_offset_dbu = design.micronToDBU(0) # Offset is 0
            # API 14: Create the PDN stripes generating pattern
            pdngen.makeStrap(grid=g,
                            layer=m4,
                            width=m4_width_dbu,
                            spacing=m4_spacing_dbu,
                            pitch=m4_pitch_dbu,
                            offset=m4_offset_dbu,
                            number_of_straps=0, # Auto-calculate number
                            snap=False, # Not specified, use False
                            starts_with=pdn.GRID, # Start based on grid pattern
                            extend=pdn.CORE, # Extend within core
                            nets=[]) # Apply to all nets in the grid (VDD/VSS)

            # Create power straps on metal7 for standard cells
            m7_width_um = 1.4
            m7_spacing_um = 1.4
            m7_pitch_um = 10.8
            m7_width_dbu = design.micronToDBU(m7_width_um)
            m7_spacing_dbu = design.micronToDBU(m7_spacing_um)
            m7_pitch_dbu = design.micronToDBU(m7_pitch_um)
            m7_offset_dbu = design.micronToDBU(0) # Offset is 0
            pdngen.makeStrap(grid=g,
                            layer=m7,
                            width=m7_width_dbu,
                            spacing=m7_spacing_dbu,
                            pitch=m7_pitch_dbu,
                            offset=m7_offset_dbu,
                            number_of_straps=0,
                            snap=False,
                            starts_with=pdn.GRID,
                            extend=pdn.CORE,
                            nets=[])

            # Create power straps on metal8 for standard cells
            m8_width_um = 1.4
            m8_spacing_um = 1.4 # Assuming spacing is also 1.4 as not specified otherwise
            m8_pitch_um = 10.8 # Assuming pitch is also 10.8 as not specified otherwise
            m8_width_dbu = design.micronToDBU(m8_width_um)
            m8_spacing_dbu = design.micronToDBU(m8_spacing_um)
            m8_pitch_dbu = design.micronToDBU(m8_pitch_um)
            m8_offset_dbu = design.micronToDBU(0) # Offset is 0
            pdngen.makeStrap(grid=g,
                            layer=m8,
                            width=m8_width_dbu,
                            spacing=m8_spacing_dbu,
                            pitch=m8_pitch_dbu,
                            offset=m8_offset_dbu,
                            number_of_straps=0,
                            snap=False,
                            starts_with=pdn.GRID,
                            extend=pdn.CORE,
                            nets=[])

            # Create power rings on M7 and M8 around the core area
            m7_ring_width_um = 2
            m7_ring_spacing_um = 2
            m8_ring_width_um = 2
            m8_ring_spacing_um = 2
            m7_ring_width_dbu = design.micronToDBU(m7_ring_width_um)
            m7_ring_spacing_dbu = design.micronToDBU(m7_ring_spacing_um)
            m8_ring_width_dbu = design.micronToDBU(m8_ring_width_um)
            m8_ring_spacing_dbu = design.micronToDBU(m8_ring_spacing_um)
            ring_offset = [design.micronToDBU(0) for i in range(4)] # Offset is 0
            ring_pad_offset = [design.micronToDBU(0) for i in range(4)] # Not specified, use 0
            ring_connect_pad_layers = [] # Not specified to connect to pads

            # API 6: Create the PDN ring around the design or the macro
            pdngen.makeRing(grid=g,
                           layer0=m7, width0=m7_ring_width_dbu, spacing0=m7_ring_spacing_dbu,
                           layer1=m8, width1=m8_ring_width_dbu, spacing1=m8_ring_spacing_dbu,
                           starts_with=pdn.GRID,
                           offset=ring_offset,
                           pad_offset=ring_pad_offset,
                           extend=False, # Rings stay within core boundary by default
                           pad_pin_layers=ring_connect_pad_layers,
                           nets=[])

            # Create via connections between core grid layers
            # API 15: Connect the stripes between two metal layers (creating vias)
            if m1 and m4:
                pdngen.makeConnect(grid=g, layer0=m1, layer1=m4,
                                   cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1],
                                   vias=[], techvias=[], max_rows=0, max_columns=0,
                                   ongrid=[], split_cuts=dict(), dont_use_vias="")
            if m4 and m7:
                 pdngen.makeConnect(grid=g, layer0=m4, layer1=m7,
                                   cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1],
                                   vias=[], techvias=[], max_rows=0, max_columns=0,
                                   ongrid=[], split_cuts=dict(), dont_use_vias="")
            if m7 and m8:
                 pdngen.makeConnect(grid=g, layer0=m7, layer1=m8,
                                   cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1],
                                   vias=[], techvias=[], max_rows=0, max_columns=0,
                                   ongrid=[], split_cuts=dict(), dont_use_vias="")


    # Create power grid for macro blocks if any exist
    macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
    if macros and m5 and m6:
        # Code Piece 3: Template of creating power distribute networks (PDN) for macros
        # Use the same macro halo for PDN area exclusion
        macro_pdn_halo = [macro_halo_dbu] * 4 # Apply halo to all sides

        m5_strap_width_um = 1.2
        m5_strap_spacing_um = 1.2
        m5_strap_pitch_um = 6
        m6_strap_width_um = 1.2
        m6_strap_spacing_um = 1.2
        m6_strap_pitch_um = 6

        m5_strap_width_dbu = design.micronToDBU(m5_strap_width_um)
        m5_strap_spacing_dbu = design.micronToDBU(m5_strap_spacing_um)
        m5_strap_pitch_dbu = design.micronToDBU(m5_strap_pitch_um)
        m6_strap_width_dbu = design.micronToDBU(m6_strap_width_um)
        m6_strap_spacing_dbu = design.micronToDBU(m6_strap_spacing_um)
        m6_strap_pitch_dbu = design.micronToDBU(m6_strap_pitch_um)
        strap_offset_dbu = design.micronToDBU(0) # Offset is 0

        m5_ring_width_um = 2
        m5_ring_spacing_um = 2
        m6_ring_width_um = 2
        m6_ring_spacing_um = 2
        m5_ring_width_dbu = design.micronToDBU(m5_ring_width_um)
        m5_ring_spacing_dbu = design.micronToDBU(m5_ring_spacing_um)
        m6_ring_width_dbu = design.micronToDBU(m6_ring_width_um)
        m6_ring_spacing_dbu = design.micronToDBU(m6_ring_spacing_um)
        macro_ring_offset = [design.micronToDBU(0) for i in range(4)] # Offset is 0
        macro_ring_pad_offset = [design.micronToDBU(0) for i in range(4)] # Not specified, use 0
        macro_ring_connect_pad_layers = [] # Not specified to connect to pads


        for i in range(len(macros)):
            macro_inst = macros[i]
            # Create separate power grid for each macro instance
            for domain in domains: # Associate with the core domain
                pdngen.makeInstanceGrid(domain=domain,
                                        name=f"macro_grid_{macro_inst.getName()}",
                                        starts_with=pdn.GROUND,
                                        inst=macro_inst,
                                        halo=macro_pdn_halo,
                                        pg_pins_to_boundary=True, # Connect macro PG pins to boundary
                                        default_grid=False,
                                        generate_obstructions=[],
                                        is_bump=False)

            macro_grid = pdngen.findGrid(f"macro_grid_{macro_inst.getName()}")
            if macro_grid:
                for g in macro_grid:
                    # Create power rings on M5 and M6 around the macro
                    pdngen.makeRing(grid=g,
                                    layer0=m5, width0=m5_ring_width_dbu, spacing0=m5_ring_spacing_dbu,
                                    layer1=m6, width1=m6_ring_width_dbu, spacing1=m6_ring_spacing_dbu,
                                    starts_with=pdn.GRID,
                                    offset=macro_ring_offset,
                                    pad_offset=macro_ring_pad_offset,
                                    extend=False, # Rings around the macro
                                    pad_pin_layers=macro_ring_connect_pad_layers,
                                    nets=[])

                    # Create power straps on metal5 for macro connections
                    pdngen.makeStrap(grid=g,
                                    layer=m5,
                                    width=m5_strap_width_dbu,
                                    spacing=m5_strap_spacing_dbu,
                                    pitch=m5_strap_pitch_dbu,
                                    offset=strap_offset_dbu,
                                    number_of_straps=0,
                                    snap=True, # Snap to grid (common for macro grids)
                                    starts_with=pdn.GRID,
                                    extend=pdn.RINGS, # Extend to cover the rings
                                    nets=[])
                    # Create power straps on metal6 for macro connections
                    pdngen.makeStrap(grid=g,
                                    layer=m6,
                                    width=m6_strap_width_dbu,
                                    spacing=m6_strap_spacing_dbu,
                                    pitch=m6_strap_pitch_dbu,
                                    offset=strap_offset_dbu,
                                    number_of_straps=0,
                                    snap=True,
                                    starts_with=pdn.GRID,
                                    extend=pdn.RINGS,
                                    nets=[])

                    # Create via connections between macro power grid layers and core grid layers
                    # Connect core grid (M4) to macro grid (M5)
                    if m4 and m5:
                        pdngen.makeConnect(grid=g, layer0=m4, layer1=m5,
                                        cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1],
                                        vias=[], techvias=[], max_rows=0, max_columns=0,
                                        ongrid=[], split_cuts=dict(), dont_use_vias="")
                    # Connect macro grid layers (M5 to M6)
                    if m5 and m6:
                         pdngen.makeConnect(grid=g, layer0=m5, layer1=m6,
                                        cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1],
                                        vias=[], techvias=[], max_rows=0, max_columns=0,
                                        ongrid=[], split_cuts=dict(), dont_use_vias="")
                    # Connect macro grid (M6) to core grid (M7)
                    if m6 and m7:
                         pdngen.makeConnect(grid=g, layer0=m6, layer1=m7,
                                        cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1],
                                        vias=[], techvias=[], max_rows=0, max_columns=0,
                                        ongrid=[], split_cuts=dict(), dont_use_vias="")
    elif macros:
        print("Warning: Metal layers M5 or M6 not found for macro PDN.")


    # Verify and build power grid
    # Check the PDN setup
    pdngen.checkSetup()
    # Build the PDN geometries
    pdngen.buildGrids(False) # False means do not generate obstructions
    # Write the generated PDN shapes to the design database
    pdngen.writeToDb(True) # True means commit the shapes
    # Reset temporary shapes used during generation
    pdngen.resetShapes()


# 7. Analysis
# Perform IR drop analysis on M1 nodes (specific layer analysis might require Tcl)
# A standard IR drop analysis
if VDD_net and VSS_net:
    # Run IR drop analysis
    # The -output option saves the report to a file.
    # Analyzing specifically M1 nodes via Python API isn't directly exposed,
    # typically done through Tcl commands with layer filtering or result parsing.
    # Let's run a basic analysis and save the report.
    print("Running IR Drop Analysis...")
    design.evalTclString("analyze_irdrop -power_net VDD -ground_net VSS -output ir_report.rpt")
    print("IR Drop Analysis complete. Report saved to ir_report.rpt")
else:
    print("Warning: VDD or VSS net not found for IR drop analysis.")


# Report power consumption
# Running power analysis. OpenROAD typically needs SPEF/parasitics for accurate power.
# Assuming parasitics are available or timing is done.
# Let's run a basic power report after CTS/Placement.
print("Reporting Power...")
# The -outfile option saves the report to a file.
design.evalTclString("report_power -outfile power_report.rpt")
print("Power report saved to power_report.rpt")


# 8. Routing
# Configure and run global routing
grt = design.getGlobalRouter()

# Find routing layer levels
min_route_layer = design.getTech().getDB().getTech().findLayer("metal1")
max_route_layer = design.getTech().getDB().getTech().findLayer("metal6")

if min_route_layer and max_route_layer:
    min_route_level = min_route_layer.getRoutingLevel()
    max_route_level = max_route_layer.getRoutingLevel()

    # Set routing layer range for global router
    grt.setMinRoutingLayer(min_route_level)
    grt.setMaxRoutingLayer(max_route_level)

    # Global router settings (adjustments, verbosity - not specified, using defaults or Example 1)
    # Example 1 used adjustment 0.5 and verbose True. Let's stick to defaults if not specified.
    # grt.setAdjustment(0.5)
    # grt.setVerbose(True)

    # Set iteration count for global router (explicitly requested 10)
    grt.setIterations(10)

    # Run global routing
    grt.globalRoute(True) # True means estimate wire RC

    # Configure and run detailed routing
    drter = design.getTritonRoute()
    params = drt.ParamStruct()

    # Set routing layer range for detailed router
    # Note: Detailed router params use layer names, not levels
    params.bottomRoutingLayer = min_route_layer.getName()
    params.topRoutingLayer = max_route_layer.getName()

    # Default detailed routing parameters (using defaults or minimal necessary)
    # params.enableViaGen = True # Default is usually True
    # params.drouteEndIter = 1 # Default is usually 1
    # params.verbose = 1 # Default verbosity

    drter.setParams(params)

    # Run detailed routing
    # API 17: Get the detailed router, then drter.main()
    drter.main()

else:
    print("Error: Could not find metal1 or metal6 for routing.")


# 9. Output
# Write final DEF file
design.writeDef("final.def")

print("Physical design flow complete. Output saved to final.def, ir_report.rpt, power_report.rpt")