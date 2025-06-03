import odb
import pdn
import drt
import openroad as ord

# Get the design object
design = ord.get_design()

# 1. Clock Definition & Propagation
# Define the clock signal with a period of 20 ns on the 'clk' port
clock_period_ns = 20
clock_period_ps = clock_period_ns * 1000 # Convert ns to ps for Tcl command
port_name = "clk" # Assuming the clock port is named 'clk'
clock_name = "core_clock"
# Create clock signal at the specified port with the given period and name
design.evalTclString("create_clock -period %s [get_ports %s] -name %s" % (clock_period_ps, port_name, clock_name))

# Propagate the clock signal
# This command makes the clock source aware of the clock definition
design.evalTclString("set_propagated_clock [get_clocks {%s}]" % clock_name)

# Set unit resistance and capacitance values for clock and signal nets
# These values are used by timing analysis and potentially routing/CTS
design.evalTclString("set_wire_rc -clock -resistance 0.03574 -capacitance 0.07516")
design.evalTclString("set_wire_rc -signal -resistance 0.03574 -capacitance 0.07516")

# 2. Floorplanning
# Initialize floorplan
floorplan = design.getFloorplan()

# Define core area based on a default size (e.g., 50x40um) and add 5um margin for die area
# This calculates die area based on core + 5um margin on all sides
core_lx_um = 5.0
core_ly_um = 5.0
core_ux_um = 55.0 # 50 + 5
core_uy_um = 45.0 # 40 + 5
margin_um = 5.0

# Calculate die coordinates based on core and margin
die_lx_um = core_lx_um - margin_um
die_ly_um = core_ly_um - margin_um
die_ux_um = core_ux_um + margin_um
die_uy_um = core_uy_um + margin_um

# Convert dimensions from microns to DBU (Database Units)
core_lx_dbu = design.micronToDBU(core_lx_um)
core_ly_dbu = design.micronToDBU(core_ly_um)
core_ux_dbu = design.micronToDBU(core_ux_um)
core_uy_dbu = design.micronToDBU(core_uy_um)

die_lx_dbu = design.micronToDBU(die_lx_um)
die_ly_dbu = design.micronToDBU(die_ly_um)
die_ux_dbu = design.micronToDBU(die_ux_um)
die_uy_dbu = design.micronToDBU(die_uy_um)

# Create odb.Rect objects for die and core areas
die_area = odb.Rect(die_lx_dbu, die_ly_dbu, die_ux_dbu, die_uy_dbu)
core_area = odb.Rect(core_lx_dbu, core_ly_dbu, core_ux_dbu, core_uy_dbu)

# Find the core site from the technology library (replace with actual site name)
site = floorplan.findSite("FreePDK45_38x28_10R_NP_162NW_34O") # Placeholder site name from example
if site is None:
     # Fallback: try to find any core site in the library
     site_found = False
     for lib in design.getTech().getDB().getLibs():
         for s in lib.getSites():
             if s.getClass() == "CORE":
                 site = s
                 print(f"Using site: {site.getName()}")
                 site_found = True
                 break
         if site_found:
             break
     if site is None:
         print("Error: No CORE site found in the library!")
         # Depending on requirements, you might exit or raise an error here
         # For now, print error and continue, which might lead to issues later
         pass # Allow script to continue, but expect errors without a valid site

# Initialize the floorplan with the defined areas and site
floorplan.initFloorplan(die_area, core_area, site)
# Create placement tracks within the core area
floorplan.makeTracks()

# Set target utilization for placement (this is a placement parameter, stored here)
target_utilization = 0.35

# Dump DEF after floorplanning
design.writeDef("floorplan.def")

# 3. IO Pin Placement
# Configure and run I/O pin placement
io_placer = design.getIOPlacer()
io_params = io_placer.getParameters()
io_params.setRandSeed(42) # Use a fixed seed for reproducibility
io_params.setMinDistanceInTracks(False) # Use DBU for min distance
io_params.setMinDistance(design.micronToDBU(0)) # No minimum distance between pins specified
io_params.setCornerAvoidance(design.micronToDBU(0)) # No corner avoidance specified

# Place I/O pins on metal8 (horizontal) and metal9 (vertical) layers
m8 = design.getTech().getDB().getTech().findLayer("metal8")
m9 = design.getTech().getDB().getTech().findLayer("metal9")
if m8:
    io_placer.addHorLayer(m8)
else:
    print("Warning: metal8 not found for horizontal IO placement.")
if m9:
    io_placer.addVerLayer(m9)
else:
     print("Warning: metal9 not found for vertical IO placement.")

# Run the I/O placement algorithm (annealing mode)
IOPlacer_random_mode = True # Enable randomness
io_placer.runAnnealing(IOPlacer_random_mode)

# Dump DEF after IO placement
design.writeDef("io_placed.def")

# 4. Macro Placement
# Identify macro blocks (instances whose master is a block/macro)
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
macro_halo_um = 5.0 # Halo region width around each macro
macro_min_distance_um = 5.0 # Requested minimum distance between macros (often influenced by halo/placer)

if len(macros) > 0:
    print(f"Found {len(macros)} macros. Performing macro placement.")
    mpl = design.getMacroPlacer()
    block = design.getBlock()
    core = block.getCoreArea() # Get the core area defined during floorplanning

    # Configure and run macro placement
    mpl.place(
        num_threads = 64, # Use multiple threads
        max_num_macro = len(macros), # Place all macros
        min_num_macro = 0,
        max_num_inst = 0, # Do not place standard cells with macro placer
        min_num_inst = 0,
        tolerance = 0.1, # Convergence tolerance
        max_num_level = 2, # Number of partitioning levels
        coarsening_ratio = 10.0, # Ratio for coarsening
        large_net_threshold = 50, # Threshold for identifying large nets
        signature_net_threshold = 50, # Threshold for signature nets
        halo_width = macro_halo_um, # Set macro halo width in microns
        halo_height = macro_halo_um, # Set macro halo height in microns
        # Fence region usually constrains macros within the core area
        fence_lx = block.dbuToMicrons(core.xMin()),
        fence_ly = block.dbuToMicrons(core.yMin()),
        fence_ux = block.dbuToMicrons(core.xMax()),
        fence_uy = block.dbuToMicrons(core.yMax()),
        area_weight = 0.1, # Weight for area objective
        outline_weight = 100.0, # Weight for outline objective
        wirelength_weight = 100.0, # Weight for wirelength objective
        guidance_weight = 10.0, # Weight for guidance
        fence_weight = 10.0, # Weight for fence constraint
        boundary_weight = 50.0, # Weight for boundary constraint
        notch_weight = 10.0, # Weight for notch constraint
        macro_blockage_weight = 10.0, # Weight for macro blockage
        pin_access_th = 0.0, # Pin access threshold
        target_util = target_utilization, # Target utilization for standard cell area estimation
        target_dead_space = 0.05, # Target dead space percentage
        min_ar = 0.33, # Minimum aspect ratio for blocks
        snap_layer = 4, # Layer to snap macro pins to grid (placeholder/example value)
        bus_planning_flag = False, # Disable bus planning
        report_directory = "" # No report directory
    )
    # Dump DEF after macro placement
    design.writeDef("macro_placed.def")
else:
    print("No macros found. Skipping macro placement.")


# 5. Standard Cell Placement (Global & Detailed)
# Configure and run global placement (Replace)
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Placement is not timing driven in this flow
gpl.setRoutabilityDrivenMode(True) # Placement is routability driven
gpl.setUniformTargetDensityMode(True) # Use uniform target density
# Set the target density for standard cells
gpl.setTargetDensity(target_utilization)

# Limit initial placement iterations as requested (assuming applies to placer)
initial_place_iterations = 10
gpl.setInitialPlaceMaxIter(initial_place_iterations)
gpl.setInitDensityPenalityFactor(0.05) # Set initial density penalty factor

# Perform initial and Nesterov global placement
gpl.doInitialPlace(threads = 4) # Run initial coarse placement
gpl.doNesterovPlace(threads = 4) # Run Nesterov-based legalization
gpl.reset() # Reset the placer state

# Run initial detailed placement (OpenDP)
# Get the site dimensions from the row to convert displacement to site units if needed
site = design.getBlock().getRows()[0].getSite() # Assuming at least one row exists

# Allow specified maximum displacement in microns, convert to DBU
max_disp_x_um = 1.0
max_disp_y_um = 3.0
max_disp_x_dbu = int(design.micronToDBU(max_disp_x_um))
max_disp_y_dbu = int(design.micronToDBU(max_disp_y_um))

# Remove any filler cells that might exist from previous steps
design.getOpendp().removeFillers()

# Perform detailed placement
# The API expects max displacement in DBU
design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False) # The last two args are debug flags

# Dump DEF after placement (includes macro and standard cell placement)
design.writeDef("placed.def")


# 6. Clock Tree Synthesis (CTS)
# Configure and run CTS (TritonCTS)
cts = design.getTritonCts()
cts_params = cts.getParms()
# Set wire segment unit (arbitrary value, common in examples)
cts_params.setWireSegmentUnit(20)

# Set the clock net to be synthesized
# Returns 1 if clock net not found, 0 if successful
if cts.setClockNets(clock_name) != 0:
    print(f"Error: Clock net '{clock_name}' not found for CTS.")
    # If clock net is not found, CTS might fail. You might want to exit here.
    # For this script, we print a warning and proceed.

# Configure the clock buffer cells to be used for synthesis
buffer_cell = "BUF_X2" # Specified buffer cell name
cts.setBufferList(buffer_cell) # Set list of available buffers
cts.setRootBuffer(buffer_cell) # Set buffer for the clock root
cts.setSinkBuffer(buffer_cell) # Set buffer for the clock sinks (flip-flops, etc.)

# Run CTS
cts.runTritonCts()

# Dump DEF after CTS
design.writeDef("cts.def")


# 7. Power Delivery Network (PDN)
pdngen = design.getPdnGen()

# Set up global power/ground connections
# Find existing power and ground nets or create if needed
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")

# Create VDD/VSS nets if they don't exist and ensure they are marked as special POWER/GROUND nets
if VDD_net is None:
    VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
if VDD_net.getSigType() != "POWER": # Ensure correct signal type
     VDD_net.setSigType("POWER")
if not VDD_net.isSpecial(): # Ensure net is special
    VDD_net.setSpecial()

if VSS_net is None:
    VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
if VSS_net.getSigType() != "GROUND": # Ensure correct signal type
    VSS_net.setSigType("GROUND")
if not VSS_net.isSpecial(): # Ensure net is special
     VSS_net.setSpecial()

# Add global connections to tie standard cell and macro power pins to the VDD/VSS nets
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDPE$", net = VDD_net, do_connect = True) # Example common VDD pin
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDCE$", net = VDD_net, do_connect = True) # Example common VDD pin
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSSE$", net = VSS_net, do_connect = True) # Example common VSS pin

# Apply the global connections
design.getBlock().globalConnect()

# Configure power domains (typically just one core domain)
switched_power_net = None # No switched power domain specified
secondary_nets = list() # No secondary power nets specified

# Set the core voltage domain
pdngen.setCoreDomain(power = VDD_net,
    swched_power = switched_power_net, # Use correct parameter name 'swched_power'
    ground = VSS_net,
    secondary = secondary_nets)

# Get the configured core domain
domains = [d for d in pdngen.getDomains() if d.isCore()]
if not domains:
     print("Error: No core domain found after setCoreDomain. Cannot build PDN.")
     # Handle error - exit or raise exception
else:
    # Get required metal layers for PDN construction
    m1 = design.getTech().getDB().getTech().findLayer("metal1")
    m4 = design.getTech().getDB().getTech().findLayer("metal4")
    m5 = design.getTech().getDB().getTech().findLayer("metal5")
    m6 = design.getTech().getDB().getTech().findLayer("metal6")
    m7 = design.getTech().getDB().getTech().findLayer("metal7")
    m8 = design.getTech().getDB().getTech().findLayer("metal8")

    # Check if all necessary layers were found
    required_layers = [m1, m4, m7, m8] # Layers for core/stdcell grid and rings
    if len(macros) > 0:
        required_layers.extend([m5, m6]) # Add layers for macro grid/rings if macros exist

    if not all(required_layers):
        print("Error: One or more specified metal layers for PDN not found. Cannot build PDN.")
        # Handle error - exit or raise exception
    else:
        # Set via cut pitch to 0 μm for parallel grids connection as requested
        via_cut_pitch_x = design.micronToDBU(0)
        via_cut_pitch_y = design.micronToDBU(0)
        pdn_cut_pitch = [via_cut_pitch_x, via_cut_pitch_y] # Format for makeConnect

        # Create the main core grid structure
        core_grid_name = "core_grid"
        for domain in domains:
            pdngen.makeCoreGrid(domain = domain,
                name = core_grid_name,
                starts_with = pdn.GROUND, # Start with ground net strap
                pin_layers = [], # No specific pin layers to connect to grid
                generate_obstructions = [], # No specific obstructions
                powercell = None, # No power cells defined
                powercontrol = None, # No power control defined
                powercontrolnetwork = "STAR") # Default network type

        core_grid = pdngen.findGrid(core_grid_name)
        if not core_grid:
            print(f"Error: Core grid '{core_grid_name}' not found after creation attempt.")
            # Handle error
        else:
            # Add straps and connections to the core grid
            for g in core_grid:
                # Create horizontal power straps on metal1 following standard cell power rails (followpin)
                pdngen.makeFollowpin(grid = g,
                    layer = m1,
                    width = design.micronToDBU(0.07), # 0.07μm width
                    extend = pdn.CORE) # Extend within the core area

                # Create standard cell/core power straps on metal4
                pdngen.makeStrap(grid = g,
                    layer = m4,
                    width = design.micronToDBU(1.2), # 1.2μm width
                    spacing = design.micronToDBU(1.2), # 1.2μm spacing
                    pitch = design.micronToDBU(6), # 6μm pitch
                    offset = design.micronToDBU(0), # Offset 0
                    number_of_straps = 0, # Auto-calculate number
                    snap = False, # Don't snap straps to track? (Following example)
                    starts_with = pdn.GRID, # Relative to the grid structure
                    extend = pdn.CORE, # Extend within core
                    nets = []) # Apply to all nets in the domain (VDD/VSS)

                # Create core power straps on metal7
                pdngen.makeStrap(grid = g,
                    layer = m7,
                    width = design.micronToDBU(1.4), # 1.4μm width
                    spacing = design.micronToDBU(1.4), # 1.4μm spacing
                    pitch = design.micronToDBU(10.8), # 10.8μm pitch
                    offset = design.micronToDBU(0), # Offset 0
                    number_of_straps = 0,
                    snap = False,
                    starts_with = pdn.GRID,
                    extend = pdn.CORE, # Extend within core
                    nets = [])

                # Create core power straps on metal8
                pdngen.makeStrap(grid = g,
                    layer = m8,
                    width = design.micronToDBU(1.4), # 1.4μm width
                    spacing = design.micronToDBU(1.4), # 1.4μm spacing
                    pitch = design.micronToDBU(10.8), # 10.8μm pitch
                    offset = design.micronToDBU(0), # Offset 0
                    number_of_straps = 0,
                    snap = False,
                    starts_with = pdn.GRID,
                    extend = pdn.BOUNDARY, # Extend to boundary? (Following example for M8)
                    nets = [])

                # Create via connections between core grid layers
                pdngen.makeConnect(grid = g, layer0 = m1, layer1 = m4,
                    cut_pitch_x = via_cut_pitch_x, cut_pitch_y = via_cut_pitch_y, # Via pitch 0
                    vias = [], techvias = [], max_rows = 0, max_columns = 0,
                    ongrid = [], split_cuts = dict(), dont_use_vias = "")
                pdngen.makeConnect(grid = g, layer0 = m4, layer1 = m7,
                    cut_pitch_x = via_cut_pitch_x, cut_pitch_y = via_cut_pitch_y, # Via pitch 0
                    vias = [], techvias = [], max_rows = 0, max_columns = 0,
                    ongrid = [], split_cuts = dict(), dont_use_vias = "")
                pdngen.makeConnect(grid = g, layer0 = m7, layer1 = m8,
                    cut_pitch_x = via_cut_pitch_x, cut_pitch_y = via_cut_pitch_y, # Via pitch 0
                    vias = [], techvias = [], max_rows = 0, max_columns = 0,
                    ongrid = [], split_cuts = dict(), dont_use_vias = "")

            # Create core power rings (around the core area)
            # Ring on M7 (2um width, 2um spacing)
            # makeRing uses layer0 and layer1 for two potentially different layers,
            # but can be used for a single layer ring by setting both to the same layer.
            pdngen.makeRing(grid = g,
                layer0 = m7, width0 = design.micronToDBU(2), spacing0 = design.micronToDBU(2),
                layer1 = m7, width1 = design.micronToDBU(2), spacing1 = design.micronToDBU(2), # Single layer ring
                starts_with = pdn.GRID, # Relation to the grid structure
                offset = [design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0)], # Offset 0
                pad_offset = [design.micronToDBU(0), design.micronToDBU(0)], # Pad offset 0
                extend = False, # Do not extend beyond the defined boundary (implicitly core boundary for core grid)
                pad_pin_layers = [], # No pad pin layers to connect to
                nets = []) # Apply to all nets in the domain

            # Ring on M8 (2um width, 2um spacing)
            pdngen.makeRing(grid = g,
                layer0 = m8, width0 = design.micronToDBU(2), spacing0 = design.micronToDBU(2),
                layer1 = m8, width1 = design.micronToDBU(2), spacing1 = design.micronToDBU(2), # Single layer ring
                starts_with = pdn.GRID,
                offset = [design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0)], # Offset 0
                pad_offset = [design.micronToDBU(0), design.micronToDBU(0)], # Pad offset 0
                extend = False,
                pad_pin_layers = [],
                nets = [])

        # Create power grid and rings for macro blocks (if present)
        if len(macros) > 0:
            print("Configuring PDN for macros.")
            macro_halo_dbu = [design.micronToDBU(macro_halo_um) for i in range(4)] # Convert halo to DBU

            for i, macro_inst in enumerate(macros):
                macro_grid_name = f"macro_grid_{macro_inst.getName()}" # Unique name per macro instance
                # Create separate power grid structure for each macro instance
                for domain in domains: # Associate with the core domain
                    pdngen.makeInstanceGrid(domain = domain,
                        name = macro_grid_name,
                        starts_with = pdn.GROUND, # Start with ground
                        inst = macro_inst, # The macro instance to build the grid around
                        halo = macro_halo_dbu, # Apply halo around macro
                        pg_pins_to_boundary = True, # Connect macro PG pins to boundary of its instance grid
                        default_grid = False, # This is an instance-specific grid
                        generate_obstructions = [],
                        is_bump = False) # Not a bump grid

                macro_grid = pdngen.findGrid(macro_grid_name)
                if not macro_grid:
                     print(f"Error: Macro grid '{macro_grid_name}' not found after creation attempt.")
                     continue # Skip this macro if grid creation failed

                for g in macro_grid:
                    # Create power straps on metal5 for macro connections
                    pdngen.makeStrap(grid = g,
                        layer = m5,
                        width = design.micronToDBU(1.2), # 1.2um width
                        spacing = design.micronToDBU(1.2), # 1.2um spacing
                        pitch = design.micronToDBU(6), # 6um pitch
                        offset = design.micronToDBU(0), # Offset 0
                        number_of_straps = 0,
                        snap = True, # Snap straps to grid (Following example)
                        starts_with = pdn.GRID,
                        extend = pdn.CORE, # Extend within macro grid's area
                        nets = [])

                    # Create power straps on metal6 for macro connections
                    pdngen.makeStrap(grid = g,
                        layer = m6,
                        width = design.micronToDBU(1.2), # 1.2um width
                        spacing = design.micronToDBU(1.2), # 1.2um spacing
                        pitch = design.micronToDBU(6), # 6um pitch
                        offset = design.micronToDBU(0), # Offset 0
                        number_of_straps = 0,
                        snap = True,
                        starts_with = pdn.GRID,
                        extend = pdn.CORE,
                        nets = [])

                    # Create via connections for macro PDN layers
                    # M4 (from core grid) to M5 (macro grid)
                    pdngen.makeConnect(grid = g, layer0 = m4, layer1 = m5,
                        cut_pitch_x = via_cut_pitch_x, cut_pitch_y = via_cut_pitch_y, # Via pitch 0
                        vias = [], techvias = [], max_rows = 0, max_columns = 0,
                        ongrid = [], split_cuts = dict(), dont_use_vias = "")
                    # M5 to M6 (macro grid layers)
                    pdngen.makeConnect(grid = g, layer0 = m5, layer1 = m6,
                        cut_pitch_x = via_cut_pitch_x, cut_pitch_y = via_cut_pitch_y, # Via pitch 0
                        vias = [], techvias = [], max_rows = 0, max_columns = 0,
                        ongrid = [], split_cuts = dict(), dont_use_vias = "")
                    # M6 (macro grid) to M7 (core grid)
                    pdngen.makeConnect(grid = g, layer0 = m6, layer1 = m7,
                        cut_pitch_x = via_cut_pitch_x, cut_pitch_y = via_cut_pitch_y, # Via pitch 0
                        vias = [], techvias = [], max_rows = 0, max_columns = 0,
                        ongrid = [], split_cuts = dict(), dont_use_vias = "")

                    # Create macro power rings (around the macro instance boundary)
                    # Ring on M5 (1.5um width, 1.5um spacing)
                    pdngen.makeRing(grid = g,
                        layer0 = m5, width0 = design.micronToDBU(1.5), spacing0 = design.micronToDBU(1.5),
                        layer1 = m5, width1 = design.micronToDBU(1.5), spacing1 = design.micronToDBU(1.5), # Single layer ring
                        starts_with = pdn.GRID,
                        offset = [design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0)], # Offset 0
                        pad_offset = [design.micronToDBU(0), design.micronToDBU(0)], # Pad offset 0
                        extend = False, # Do not extend
                        pad_pin_layers = [],
                        nets = [])

                    # Ring on M6 (1.5um width, 1.5um spacing)
                    pdngen.makeRing(grid = g,
                        layer0 = m6, width0 = design.micronToDBU(1.5), spacing0 = design.micronToDBU(1.5),
                        layer1 = m6, width1 = design.micronToDBU(1.5), spacing1 = design.micronToDBU(1.5), # Single layer ring
                        starts_with = pdn.GRID,
                        offset = [design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0)], # Offset 0
                        pad_offset = [design.micronToDBU(0), design.micronToDBU(0)], # Pad offset 0
                        extend = False,
                        pad_pin_layers = [],
                        nets = [])


        # Verify the PDN setup and build the grids
        pdngen.checkSetup() # Check for configuration errors
        pdngen.buildGrids(False) # Build the physical shapes of the grid
        pdngen.writeToDb(True, ) # Write the generated shapes into the design database
        pdngen.resetShapes() # Clean up temporary shapes

# Dump DEF after PDN creation
design.writeDef("pdn.def")

# Insert filler cells after PDN creation and before final placement/routing
# Filler cells fill empty spaces for density and routability
db = ord.get_db()
filler_masters = list()
# Find CORE_SPACER type masters in libraries
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

if len(filler_masters) == 0:
    print("Warning: no filler cells found in library! Skipping filler placement.")
else:
    print(f"Found {len(filler_masters)} filler cells. Inserting fillers.")
    # Prefix for naming inserted filler instances
    filler_cells_prefix = "FILLCELL_"
    # Perform filler cell placement
    design.getOpendp().fillerPlacement(filler_masters = filler_masters,
                                     prefix = filler_cells_prefix,
                                     verbose = False)

# 8. IR Drop Analysis
# Perform IR drop analysis on the constructed power grid
# The 'analyze_power_grid' Tcl command runs the analysis.
# Specifying analysis on "M1 nodes" specifically might require advanced commands or output parsing.
# The basic command analyzes the entire grid.
print("Performing IR drop analysis...")
# Execute Tcl command for power grid analysis
design.evalTclString("analyze_power_grid -honor_inst_location true")
# Note: The tool's output will contain the IR drop report.
print("IR drop analysis completed.")


# 9. Power Reporting
# Report power consumption (switching, leakage, internal, total)
# This command reports various power metrics. Dynamic power reporting
# typically requires an activity file (SAIF/VCD), which is not provided
# in the prompt. The basic command might report static power and possibly
# estimated dynamic power based on defaults.
print("Reporting power...")
# Execute Tcl command to report power
design.evalTclString("report_power")
# Note: The tool's output will contain the power report breakdown
print("Power reporting completed.")


# 10. Routing (Global & Detailed)
# Configure and run global routing (GlobalRouter)
grt = design.getGlobalRouter()

# Set routing layer ranges for signal and clock nets
# Routing should be performed from M1 to M7
metal1_level = design.getTech().getDB().getTech().findLayer("metal1").getRoutingLevel()
metal7_level = design.getTech().getDB().getTech().findLayer("metal7").getRoutingLevel()

grt.setMinRoutingLayer(metal1_level) # Set the lowest layer for signal routing
grt.setMaxRoutingLayer(metal7_level) # Set the highest layer for signal routing
grt.setMinLayerForClock(metal1_level) # Set the lowest layer for clock routing
grt.setMaxLayerForClock(metal7_level) # Set the highest layer for clock routing

grt.setAdjustment(0.5) # Set routing congestion adjustment (default value)
grt.setVerbose(True) # Enable verbose output

# Run global route
grt.globalRoute(True) # Argument True enables congestion-driven global routing

# Dump DEF after global routing (contains placement and global routes)
design.writeDef("grt.def")


# Configure and run detailed routing (TritonRoute)
drter = design.getTritonRoute()
dr_params = drt.ParamStruct()

# Set detailed routing parameters
dr_params.outputMazeFile = "" # No debug output files specified
dr_params.outputDrcFile = ""
dr_params.outputCmapFile = ""
dr_params.outputGuideCoverageFile = ""
dr_params.dbProcessNode = "" # Optional process node
dr_params.enableViaGen = True # Enable automatic via generation
dr_params.drouteEndIter = 1 # Number of detailed routing iterations
dr_params.viaInPinBottomLayer = "" # Optional via-in-pin layer constraints
dr_params.viaInPinTopLayer = ""
dr_params.orSeed = -1 # Random seed (-1 for default)
dr_params.orK = 0 # Parameter for OR algorithm
dr_params.bottomRoutingLayer = "metal1" # Explicitly set bottom layer for detailed router
dr_params.topRoutingLayer = "metal7" # Explicitly set top layer for detailed router
dr_params.verbose = 1 # Verbosity level
dr_params.cleanPatches = True # Clean up routing patches
dr_params.doPa = True # Perform post-routing antenna fixing
dr_params.singleStepDR = False # Disable single step mode
dr_params.minAccessPoints = 1 # Minimum access points for detailed routing
dr_params.saveGuideUpdates = False # Don't save guide updates

# Set the configured parameters for the detailed router
drter.setParams(dr_params)

# Run detailed route
drter.main()

# Dump final DEF file after detailed routing (contains placement and detailed routes)
design.writeDef("final.def")

# 11. Write final Verilog file (post-layout netlist including buffers, etc.)
design.evalTclString("write_verilog final.v")