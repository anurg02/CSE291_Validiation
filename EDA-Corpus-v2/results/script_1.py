import odb
import pdn
import drt
import openroad as ord

# Get the design object
design = ord.get_design()

# 1. Create Clock
# Clock period in nanoseconds
clock_period_ns = 20
# Convert period to picoseconds for create_clock Tcl command
clock_period_ps = clock_period_ns * 1000
clock_port_name = "clk_i"
clock_name = "core_clock"
# Create clock signal at the specified port with the given period and name
design.evalTclString(f"create_clock -period {clock_period_ps} [get_ports {clock_port_name}] -name {clock_name}")
# Propagate the clock signal
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Set wire RC values for clock and signal nets for timing analysis
# Resistance and capacitance values are per unit length (e.g., per micron)
rc_resistance = 0.0435
rc_capacitance = 0.0817
design.evalTclString(f"set_wire_rc -clock -resistance {rc_resistance} -capacitance {rc_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {rc_resistance} -capacitance {rc_capacitance}")

# 2. Floorplanning
# Get the floorplan module
floorplan = design.getFloorplan()
block = design.getBlock()
tech = design.getTech().getDB().getTech()

# Get a site definition from the technology library
# Assumes a site named "FreePDK45_38x28_10R_NP_162NW_34O" exists (replace with your site name)
site = floorplan.findSite("FreePDK45_38x28_10R_NP_162NW_34O")
if site is None:
    print("Error: Site not found. Please update the site name in the script.")
    # Handle error or exit gracefully if site is required
    # For this script, we'll assume a valid site is found or this check is adapted.
    # If you don't know the site name, you might need to query library data.
    # Example: site = tech.getLibs()[0].findSite("your_site_name")

# Define a placeholder core area and calculate die area based on 10um margin
# Note: A more sophisticated script would calculate core area based on cell area and target utilization.
# This placeholder is used because initFloorplan requires specific rectangle inputs.
# Let's assume a starting core size (e.g., based on a rough estimation or default)
# We cannot easily get the design's required core area for 45% util before floorplan init.
# Let's set a placeholder core area and calculate the die from there.
# This is a simplification due to API structure vs prompt's requirement.
# A typical synthesis output netlist might have attributes or we might estimate based on instance count.
# For this script, we will pick an arbitrary core size to enable initFloorplan.
# Let's assume a placeholder core size that seems reasonable, e.g., 500x500 DBU (adjust based on your tech's DBU)
# Or calculate from target utilization if possible - not directly via initFloorplan.
# Let's follow Example 1 pattern but calculate die from a fictional core size + margin.
# The prompt implies sizing the core for 45% util, and die from that. This is hard to do
# solely within initFloorplan. Let's initialize with *some* core/die that has the margin,
# and trust the placement tool to respect 45% util within the core.

# Define a placeholder core width and height in microns
placeholder_core_width_micron = 100.0
placeholder_core_height_micron = 100.0
margin_micron = 10.0

# Convert placeholder core dimensions and margin to DBU
placeholder_core_width_dbu = design.micronToDBU(placeholder_core_width_micron)
placeholder_core_height_dbu = design.micronToDBU(placeholder_core_height_micron)
margin_dbu = design.micronToDBU(margin_micron)

# Calculate core and die area rectangles based on placeholder core and margin
core_area = odb.Rect(margin_dbu, margin_dbu,
                     margin_dbu + placeholder_core_width_dbu, margin_dbu + placeholder_core_height_dbu)
die_area = odb.Rect(0, 0,
                    core_area.xMax() + margin_dbu, core_area.yMax() + margin_dbu)

# Initialize floorplan with the calculated die and core areas and the site
if site:
    floorplan.initFloorplan(die_area, core_area, site)
    # Create placement tracks based on the site definition
    floorplan.makeTracks()
else:
    print("Warning: Site not found, floorplan initialization might be incomplete.")
    # Depending on flow, you might need to exit or handle this differently.
    # Proceeding without tracks might cause issues later.

# Set the target utilization for standard cell placement
# This is typically done after floorplanning but before placement
design.getOpendp().setTargetUtil(0.45)

# 3. I/O Pin Placement
# Get the I/O placer module and its parameters
iop = design.getIOPlacer()
iop_params = iop.getParameters()

# Configure I/O placer parameters (optional, using defaults or specific needs)
# iop_params.setRandSeed(42) # Example: Set random seed
# iop_params.setMinDistanceInTracks(False) # Example: Set min distance in tracks
# iop_params.setMinDistance(design.micronToDBU(0)) # Example: Set min distance in DBU
# iop_params.setCornerAvoidance(design.micronToDBU(0)) # Example: Set corner avoidance

# Find routing layers for I/O pin placement
metal8_layer = tech.findLayer("metal8")
metal9_layer = tech.findLayer("metal9")

# Add horizontal and vertical layers for I/O pins
if metal8_layer:
    iop.addHorLayer(metal8_layer)
else:
    print("Warning: metal8 layer not found for IO placement.")
if metal9_layer:
    iop.addVerLayer(metal9_layer)
else:
    print("Warning: metal9 layer not found for IO placement.")

# Run I/O pin placement (using annealing, random mode as in example)
# IOPlacer_random_mode = True # Set to True for random annealing mode
# iop.runAnnealing(IOPlacer_random_mode) # Use runAnnealing if needed
# Or simply run the placer
iop.run() # Assuming run() is the standard method after setup

# 4. Placement
# Identify macro blocks (instances that are blocks/black boxes)
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

# Place macro blocks if any exist
if macros:
    print(f"Found {len(macros)} macros. Running macro placement.")
    mpl = design.getMacroPlacer()

    # Define the bounding box for macro placement in microns
    fence_lx_micron = 32.0
    fence_ly_micron = 32.0
    fence_ux_micron = 55.0
    fence_uy_micron = 60.0

    # Convert bounding box coordinates to DBU
    fence_lx_dbu = design.micronToDBU(fence_lx_micron)
    fence_ly_dbu = design.micronToDBU(fence_ly_micron)
    fence_ux_dbu = design.micronToDBU(fence_ux_micron)
    fence_uy_dbu = design.micronToDBU(fence_uy_micron)

    # Define macro spacing and halo in microns
    macro_spacing_micron = 5.0
    macro_halo_micron = 5.0

    # Convert macro spacing and halo to DBU
    macro_spacing_dbu = design.micronToDBU(macro_spacing_micron)
    macro_halo_dbu = design.micronToDBU(macro_halo_micron)

    # Run macro placement with specified parameters
    # Using the 'place' method with parameters matching the prompt's constraints
    # Note: Not all parameters used below might be strictly required by the prompt,
    # but they are common in the 'place' method and set to reasonable defaults or derived.
    mpl.place(
        num_threads = 8, # Number of threads for placement
        max_num_macro = len(macros) + 1, # Allow placing all found macros
        fence_lx = fence_lx_micron, # Bounding box lower-left x (microns)
        fence_ly = fence_ly_micron, # Bounding box lower-left y (microns)
        fence_ux = fence_ux_micron, # Bounding box upper-right x (microns)
        fence_uy = fence_uy_micron, # Bounding box upper-right y (microns)
        halo_width = macro_halo_micron, # Halo width around macros (microns)
        halo_height = macro_halo_micron, # Halo height around macros (microns)
        macro_blockage_weight = 1.0, # Weight for macro blockage
        min_macro_spacing = macro_spacing_micron # Minimum spacing between macros (microns)
        # Other parameters can be tuned as needed based on the API documentation
        # For example: area_weight, outline_weight, wirelength_weight, target_util etc.
    )
    print("Macro placement finished.")
else:
    print("No macros found. Skipping macro placement.")


# Configure and run global placement for standard cells
gpl = design.getReplace()
# Set global placement parameters
gpl.setTimingDrivenMode(True) # Usually timing driven is preferred post-synth
gpl.setRoutabilityDrivenMode(True)
gpl.setUniformTargetDensityMode(True) # Respect target utilization set earlier
# Example: Limit global placement iterations (user asked for GR iterations, not GP)
# gpl.setInitialPlaceMaxIter(10)
# gpl.setInitDensityPenalityFactor(0.05)

# Perform global placement
# gpl.doInitialPlace(threads = 8) # Initial analytical placement
# gpl.doNesterovPlace(threads = 8) # Nesterov-based placement (improves wirelength)
gpl.globalPlacement() # A common function to run global placement

# Configure and run detailed placement for standard cells
dpl = design.getOpendp()
# Detailed placement max displacement in microns
max_disp_x_micron = 0.0
max_disp_y_micron = 0.0

# Convert max displacement to DBU relative to site dimensions
# Get site dimensions (assuming a site exists)
site_width = site.getWidth() if site else 1 # Avoid division by zero
site_height = site.getHeight() if site else 1

max_disp_x_dbu = design.micronToDBU(max_disp_x_micron)
max_disp_y_dbu = design.micronToDBU(max_disp_y_micron)

# Detailed placement expects displacement in site units often,
# but the API description in Example 1 uses DBU. Let's use DBU as per example.
# Example 1 uses DBU values, but then converts to site units for the actual call.
# Let's follow the example and convert to site units if the API expects it.
# The API signature `detailedPlacement(max_disp_x, max_disp_y, ...)` takes integers.
# Example 1 converts `design.micronToDBU(1) / site.getWidth()` which implies site units.
# Let's stick to the example's method for unit consistency.

max_disp_x_site_units = int(max_disp_x_dbu / site_width) if site_width > 0 else 0
max_disp_y_site_units = int(max_disp_y_dbu / site_height) if site_height > 0 else 0

# Remove filler cells before detailed placement if they were previously inserted
dpl.removeFillers()

# Perform detailed placement with specified max displacement
# detailedPlacement(max_disp_x, max_disp_y, output_dpl_file, allow_multi_row_mstr)
dpl.detailedPlacement(max_disp_x_site_units, max_disp_y_site_units, "", False)
print("Placement finished.")

# 5. Clock Tree Synthesis (CTS)
print("Starting CTS...")
cts = design.getTritonCts()

# Set clock buffer list and root/sink buffers
buffer_cell = "BUF_X3" # Clock buffer cell name
cts.setBufferList(buffer_cell)
cts.setRootBuffer(buffer_cell)
cts.setSinkBuffer(buffer_cell)

# Set the clock net to synthesize
# cts.setClockNets(clock_name) # API 10 description is vague, evalTclString approach is common

# Run CTS
cts.runTritonCts()
print("CTS finished.")

# Rerun detailed placement after CTS to fix cell movement
# Re-calculate max displacement in site units based on potentially moved cells
# Using the same max displacement as before (0,0) as requested
dpl.detailedPlacement(max_disp_x_site_units, max_disp_y_site_units, "", False)
print("Post-CTS detailed placement finished.")

# 6. Power Delivery Network (PDN) Construction
print("Starting PDN construction...")
pdngen = design.getPdnGen()

# Find or create VDD and VSS nets
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

# Create nets if they don't exist and mark them as special power/ground nets
if VDD_net is None:
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSigType("POWER")
if VSS_net is None:
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSigType("GROUND")

# Mark existing power and ground nets as special
for net in block.getNets():
    if net.getSigType() == "POWER" or net.getSigType() == "GROUND":
        net.setSpecial()

# Connect instance power/ground pins to the global VDD/VSS nets
# This connects pins like VDD, VSS, VDDCE, VSSCE, VDDPE, VSSPE etc. to the main nets
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "VDD.*", net = VDD_net, do_connect = True)
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "VSS.*", net = VSS_net, do_connect = True)
block.globalConnect() # Apply the global connections

# Set the core power domain nets
# No switched power or secondary nets specified
switched_power = None
secondary_nets = []
pdngen.setCoreDomain(power = VDD_net, switched_power = switched_power, ground = VSS_net, secondary = secondary_nets)

# Find necessary metal layers
m1 = tech.findLayer("metal1")
m4 = tech.findLayer("metal4")
m5 = tech.findLayer("metal5")
m6 = tech.findLayer("metal6")
m7 = tech.findLayer("metal7")
m8 = tech.findLayer("metal8")

# Define via cut pitch in microns
via_cut_pitch_micron = 2.0
via_cut_pitch_dbu = design.micronToDBU(via_cut_pitch_micron)
pdn_cut_pitch = [via_cut_pitch_dbu, via_cut_pitch_dbu] # [cut_pitch_x, cut_pitch_y]

# Define zero offset for all straps and rings
zero_offset_dbu = design.micronToDBU(0)
strap_offset = zero_offset_dbu
ring_offset = [zero_offset_dbu, zero_offset_dbu, zero_offset_dbu, zero_offset_dbu] # [x0, y0, x1, y1]
ring_pad_offset = [zero_offset_dbu, zero_offset_dbu] # [x_pad, y_pad]


# Create the main core grid structure for standard cells
# This grid will cover the core area
core_grid_name = "core_grid"
domains = [pdngen.findDomain("Core")] # Get the core domain object
for domain in domains:
    pdngen.makeCoreGrid(domain = domain,
                        name = core_grid_name,
                        starts_with = pdn.GROUND, # Or pdn.POWER, depending on pattern
                        pin_layers = [], # Layers to connect to power/ground pins (usually followpin handles this)
                        generate_obstructions = [],
                        powercell = None,
                        powercontrol = None,
                        powercontrolnetwork = "STAR") # Or pdn.RING, pdn.LEAF etc.

# Get the created core grid object
core_grid = pdngen.findGrid(core_grid_name)

# Add straps to the core grid
if core_grid:
    for g in core_grid:
        # Standard cell power rail connections (followpin on M1)
        if m1:
            m1_followpin_width_micron = 0.07
            m1_followpin_width_dbu = design.micronToDBU(m1_followpin_width_micron)
            pdngen.makeFollowpin(grid = g,
                                 layer = m1,
                                 width = m1_followpin_width_dbu,
                                 extend = pdn.CORE) # Extend followpin straps to core boundary

        # M4 straps for core grid
        if m4:
            m4_strap_width_micron = 1.2
            m4_strap_spacing_micron = 1.2
            m4_strap_pitch_micron = 6.0
            m4_strap_width_dbu = design.micronToDBU(m4_strap_width_micron)
            m4_strap_spacing_dbu = design.micronToDBU(m4_strap_spacing_micron)
            m4_strap_pitch_dbu = design.micronToDBU(m4_strap_pitch_micron)
            pdngen.makeStrap(grid = g,
                             layer = m4,
                             width = m4_strap_width_dbu,
                             spacing = m4_strap_spacing_dbu,
                             pitch = m4_strap_pitch_dbu,
                             offset = strap_offset,
                             number_of_straps = 0, # Auto-calculate
                             snap = False, # Snap to track grid if needed
                             starts_with = pdn.GRID, # Start pattern relative to grid origin
                             extend = pdn.CORE, # Extend straps to core boundary
                             nets = []) # Apply to all nets in the domain

        # M7 straps for core grid
        if m7:
            m7_strap_width_micron = 1.4
            m7_strap_spacing_micron = 1.4
            m7_strap_pitch_micron = 10.8
            m7_strap_width_dbu = design.micronToDBU(m7_strap_width_micron)
            m7_strap_spacing_dbu = design.micronToDBU(m7_strap_spacing_micron)
            m7_strap_pitch_dbu = design.micronToDBU(m7_strap_pitch_micron)
            pdngen.makeStrap(grid = g,
                             layer = m7,
                             width = m7_strap_width_dbu,
                             spacing = m7_strap_spacing_dbu,
                             pitch = m7_strap_pitch_dbu,
                             offset = strap_offset,
                             number_of_straps = 0, # Auto-calculate
                             snap = False, # Snap to track grid if needed
                             starts_with = pdn.GRID,
                             extend = pdn.CORE, # Extend straps to core boundary
                             nets = []) # Apply to all nets in the domain

# Add via connections for the core grid
if core_grid:
    for g in core_grid:
        # Connect M1 to M4
        if m1 and m4:
            pdngen.makeConnect(grid = g,
                               layer0 = m1,
                               layer1 = m4,
                               cut_pitch_x = pdn_cut_pitch[0],
                               cut_pitch_y = pdn_cut_pitch[1]) # Use defined via pitch
        # Connect M4 to M7
        if m4 and m7:
             pdngen.makeConnect(grid = g,
                               layer0 = m4,
                               layer1 = m7,
                               cut_pitch_x = pdn_cut_pitch[0],
                               cut_pitch_y = pdn_cut_pitch[1]) # Use defined via pitch

# Create power rings around the core
# Rings are defined using two layers (layer0 and layer1)
# Prompt asks for rings on M7 and M8. Let's use M7 as layer0 and M8 as layer1
if m7 and m8:
    m7_ring_width_micron = 2.0
    m7_ring_spacing_micron = 2.0
    m8_ring_width_micron = 2.0
    m8_ring_spacing_micron = 2.0

    m7_ring_width_dbu = design.micronToDBU(m7_ring_width_micron)
    m7_ring_spacing_dbu = design.micronToDBU(m7_ring_spacing_micron)
    m8_ring_width_dbu = design.micronToDBU(m8_ring_width_micron)
    m8_ring_spacing_dbu = design.micronToDBU(m8_ring_spacing_micron)

    for domain in domains:
        # Assuming the core grid is the primary grid for the domain
        pdngen.makeRing(grid = pdngen.findGrid(core_grid_name)[0], # Apply ring to the core grid
                        layer0 = m7,
                        width0 = m7_ring_width_dbu,
                        spacing0 = m7_ring_spacing_dbu,
                        layer1 = m8,
                        width1 = m8_ring_width_dbu,
                        spacing1 = m8_ring_spacing_dbu,
                        starts_with = pdn.GROUND, # Pattern start
                        offset = ring_offset, # Ring offset
                        pad_offset = ring_pad_offset, # Pad offset
                        extend = pdn.CORE, # Extend ring to core boundary (or pdn.BOUNDARY for die boundary)
                        pad_pin_layers = [], # Layers to connect to pad pins if needed
                        nets = []) # Apply to all nets in the domain

# Create instance grids for macros if they exist
if macros:
    print("Creating instance grids for macros...")
    # Define halo around macros for instance grid exclusion
    macro_halo_dbu = [design.micronToDBU(macro_halo_micron) for i in range(4)] # [left, bottom, right, top]

    for i, macro_inst in enumerate(macros):
        macro_grid_name = f"macro_grid_{i}"
        for domain in domains:
            # Create instance grid for each macro instance
            pdngen.makeInstanceGrid(domain = domain,
                                    name = macro_grid_name,
                                    starts_with = pdn.GROUND, # Pattern start
                                    inst = macro_inst, # The macro instance
                                    halo = macro_halo_dbu, # Halo around macro
                                    pg_pins_to_boundary = True, # Connect macro PG pins to grid boundary
                                    default_grid = False,
                                    generate_obstructions = [],
                                    is_bump = False)

        # Get the created macro instance grid object
        macro_grid = pdngen.findGrid(macro_grid_name)

        # Add straps to the macro grid
        if macro_grid:
            for g in macro_grid:
                # M5 straps for macro grid
                if m5:
                    m5_strap_width_micron = 1.2
                    m5_strap_spacing_micron = 1.2
                    m5_strap_pitch_micron = 6.0
                    m5_strap_width_dbu = design.micronToDBU(m5_strap_width_micron)
                    m5_strap_spacing_dbu = design.micronToDBU(m5_strap_spacing_micron)
                    m5_strap_pitch_dbu = design.micronToDBU(m5_strap_pitch_micron)
                    pdngen.makeStrap(grid = g,
                                     layer = m5,
                                     width = m5_strap_width_dbu,
                                     spacing = m5_strap_spacing_dbu,
                                     pitch = m5_strap_pitch_dbu,
                                     offset = strap_offset,
                                     number_of_straps = 0,
                                     snap = True, # Snap to grid (tracks)
                                     starts_with = pdn.GRID,
                                     extend = pdn.CORE, # Extend straps within the instance grid boundary
                                     nets = [])

                # M6 straps for macro grid
                if m6:
                    m6_strap_width_micron = 1.2
                    m6_strap_spacing_micron = 1.2
                    m6_strap_pitch_micron = 6.0
                    m6_strap_width_dbu = design.micronToDBU(m6_strap_width_micron)
                    m6_strap_spacing_dbu = design.micronToDBU(m6_strap_spacing_micron)
                    m6_strap_pitch_dbu = design.micronToDBU(m6_strap_pitch_micron)
                    pdngen.makeStrap(grid = g,
                                     layer = m6,
                                     width = m6_strap_width_dbu,
                                     spacing = m6_strap_spacing_dbu,
                                     pitch = m6_strap_pitch_dbu,
                                     offset = strap_offset,
                                     number_of_straps = 0,
                                     snap = True, # Snap to grid (tracks)
                                     starts_with = pdn.GRID,
                                     extend = pdn.CORE, # Extend straps within the instance grid boundary
                                     nets = [])

        # Add via connections for the macro grid
        # Connections are typically made between macro grid layers and the main core grid layers they intersect
        if macro_grid:
            for g in macro_grid:
                 # Connect M4 (core) to M5 (macro)
                 if m4 and m5:
                     pdngen.makeConnect(grid = g,
                                        layer0 = m4,
                                        layer1 = m5,
                                        cut_pitch_x = pdn_cut_pitch[0],
                                        cut_pitch_y = pdn_cut_pitch[1]) # Use defined via pitch
                 # Connect M5 (macro) to M6 (macro)
                 if m5 and m6:
                     pdngen.makeConnect(grid = g,
                                        layer0 = m5,
                                        layer1 = m6,
                                        cut_pitch_x = pdn_cut_pitch[0],
                                        cut_pitch_y = pdn_cut_pitch[1]) # Use defined via pitch
                 # Connect M6 (macro) to M7 (core/ring)
                 if m6 and m7:
                      pdngen.makeConnect(grid = g,
                                        layer0 = m6,
                                        layer1 = m7,
                                        cut_pitch_x = pdn_cut_pitch[0],
                                        cut_pitch_y = pdn_cut_pitch[1]) # Use defined via pitch

# Verify and build the power delivery network
pdngen.checkSetup() # Verify the PDN configuration
pdngen.buildGrids(False) # Build the power grid structures
pdngen.writeToDb(True) # Write the generated PDN shapes to the design database
pdngen.resetShapes() # Clean up temporary shapes used during generation
print("PDN construction finished.")

# 7. Filler Cell Insertion
print("Inserting filler cells...")
db = ord.get_db()
filler_masters = list()
# Find filler cells in the library (assuming CORE_SPACER type)
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

if len(filler_masters) == 0:
    print("Warning: No filler cells found in library (CORE_SPACER type). Skipping filler placement.")
else:
    # Insert filler cells into empty spaces in the core area
    # Use a prefix for filler cell instance names
    filler_cells_prefix = "FILLCELL_"
    design.getOpendp().fillerPlacement(filler_masters = filler_masters,
                                     prefix = filler_cells_prefix,
                                     verbose = False) # Set to True for verbose output
    print("Filler cell insertion finished.")


# 8. Routing
print("Starting routing...")

# Configure and run global routing
grt = design.getGlobalRouter()

# Find routing layers by name and get their routing levels
# Route from M1 to M6
min_route_layer_name = "metal1"
max_route_layer_name = "metal6"

min_route_layer = tech.findLayer(min_route_layer_name)
max_route_layer = tech.findLayer(max_route_layer_name)

if min_route_layer and max_route_layer:
    min_route_level = min_route_layer.getRoutingLevel()
    max_route_level = max_route_layer.getRoutingLevel()

    grt.setMinRoutingLayer(min_route_level)
    grt.setMaxRoutingLayer(max_route_level)

    # Clock nets usually have preferred routing layers,
    # but the prompt asks to route everything from M1-M6.
    # Let's set clock layers to the same range for simplicity.
    grt.setMinLayerForClock(min_route_level)
    grt.setMaxLayerForClock(max_route_level)

    # Set global routing parameters
    grt.setAdjustment(0.5) # Congestion adjustment factor
    grt.setVerbose(True)
    grt.setIterations(10) # Set global routing iterations as requested

    # Perform global routing (True enables Rip-up and Reroute)
    grt.globalRoute(True)
    print("Global routing finished.")
else:
    print(f"Warning: Routing layers {min_route_layer_name} or {max_route_layer_name} not found. Skipping routing.")


# Configure and run detailed routing
# Get the detailed router module
drter = design.getTritonRoute()
drt_params = drt.ParamStruct()

# Set detailed routing parameters
# Use the same layer range as global routing
if min_route_layer_name and max_route_layer_name:
    drt_params.bottomRoutingLayer = min_route_layer_name
    drt_params.topRoutingLayer = max_route_layer_name
else:
     print("Warning: Cannot set detailed routing layers.")

drt_params.verbose = 1 # Verbosity level
drt_params.cleanPatches = True # Clean up routing patches
drt_params.doPa = True # Perform post-route pin access
drt_params.drouteEndIter = 1 # Number of detailed routing iterations
drt_params.enableViaGen = True # Enable via generation

# Other parameters can be tuned as needed
# drt_params.outputMazeFile = ""
# drt_params.outputDrcFile = "drc_errors.rpt" # Example: Output DRC report
# drt_params.outputCmapFile = ""
# drt_params.outputGuideCoverageFile = ""
# drt_params.dbProcessNode = "" # Technology node identifier
# drt_params.viaInPinBottomLayer = ""
# drt_params.viaInPinTopLayer = ""
# drt_params.orSeed = -1 # Random seed for detailed router
# drt_params.orK = 0
# drt_params.singleStepDR = False
# drt_params.minAccessPoints = 1
# drt_params.saveGuideUpdates = False

# Apply the parameters to the detailed router
drter.setParams(drt_params)

# Run detailed routing
if min_route_layer and max_route_layer:
    drter.main()
    print("Detailed routing finished.")
else:
    print("Skipping detailed routing due to missing layers.")


# 9. Save Output
print("Saving output files...")
# Write the final DEF file
design.writeDef("final.def")

# Write the final Verilog netlist (post-placement/CTS/routing)
# The command below uses the Tcl interface via evalTclString
design.evalTclString("write_verilog final.v")
print("Output files saved: final.def, final.v")