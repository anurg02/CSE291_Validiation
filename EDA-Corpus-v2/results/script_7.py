# Import necessary libraries for OpenROAD tools and database access
import odb
import pdn
import drt
import openroad as ord

# --- Configuration Parameters ---
clock_period_ns = 20 # Clock period in nanoseconds
clock_port_name = "clk_i" # Name of the input port for the clock
clock_net_name = "core_clock" # Internal name for the clock net
core_to_die_margin_um = 14 # Spacing between the core area and the die boundary in microns
target_utilization = 0.45 # Target standard cell utilization in the core area
io_hor_layer_name = "M8" # Horizontal IO placement layer name
io_ver_layer_name = "M9" # Vertical IO placement layer name
macro_halo_um = 5 # Halo size around macros for placement keepout and PDN exclusion/extension in microns
dp_max_disp_x_um = 0.5 # Detailed placement maximum displacement in X direction in microns
dp_max_disp_y_um = 1.0 # Detailed placement maximum displacement in Y direction in microns
cts_buffer_name = "BUF_X3" # Buffer cell name to use for Clock Tree Synthesis
wire_rc_resistance = 0.0435 # Unit resistance for clock and signal wires
wire_rc_capacitance = 0.0817 # Unit capacitance for clock and signal wires
pdn_core_grid_m1_width_um = 0.07 # Core grid M1 strap width (typically followpin) in microns
pdn_core_grid_m4_width_um = 1.2 # Core grid M4 strap width in microns
pdn_core_grid_m4_spacing_um = 1.2 # Core grid M4 strap spacing in microns
pdn_core_grid_m4_pitch_um = 6.0 # Core grid M4 strap pitch in microns
pdn_core_grid_m7_width_um = 1.4 # Core grid M7 strap width in microns
pdn_core_grid_m7_spacing_um = 1.4 # Core grid M7 strap spacing in microns
pdn_core_grid_m7_pitch_um = 10.8 # Core grid M7 strap pitch in microns
pdn_core_grid_m8_width_um = 1.4 # Core grid M8 strap width in microns
pdn_core_grid_m8_spacing_um = 1.4 # Core grid M8 strap spacing in microns
pdn_core_grid_m8_pitch_um = 10.8 # Core grid M8 strap pitch in microns
pdn_ring_m7_width_um = 2.0 # Core ring M7 width in microns
pdn_ring_m7_spacing_um = 2.0 # Core ring M7 spacing in microns
pdn_ring_m8_width_um = 2.0 # Core ring M8 width in microns
pdn_ring_m8_spacing_um = 2.0 # Core ring M8 spacing in microns
pdn_macro_grid_m5_width_um = 1.2 # Macro instance grid M5 strap width in microns
pdn_macro_grid_m5_spacing_um = 1.2 # Macro instance grid M5 strap spacing in microns
pdn_macro_grid_m5_pitch_um = 6.0 # Macro instance grid M5 strap pitch in microns
pdn_macro_grid_m6_width_um = 1.2 # Macro instance grid M6 strap width in microns
pdn_macro_grid_m6_spacing_um = 1.2 # Macro instance grid M6 strap spacing in microns
pdn_macro_grid_m6_pitch_um = 6.0 # Macro instance grid M6 strap pitch in microns
pdn_macro_ring_m5_width_um = 2.0 # Macro instance ring M5 width in microns
pdn_macro_ring_m5_spacing_um = 2.0 # Macro instance ring M5 spacing in microns
pdn_macro_ring_m6_width_um = 2.0 # Macro instance ring M6 width in microns
pdn_macro_ring_m6_spacing_um = 2.0 # Macro instance ring M6 spacing in microns
pdn_via_pitch_um = 2.0 # Via pitch for connections between parallel straps/rings on adjacent layers in microns
pdn_offset_um = 0.0 # Offset for straps/rings from their start points in microns
global_route_min_layer_name = "M1" # Minimum layer for global routing
global_route_max_layer_name = "M6" # Maximum layer for global routing
detailed_route_min_layer_name = "M1" # Minimum layer for detailed routing
detailed_route_max_layer_name = "M6" # Maximum layer for detailed routing
ir_drop_layer_name = "M1" # Target layer for IR drop analysis
output_def_file = "final.def" # Output DEF file name

# Assume technology LEF and design Verilog/DEF are loaded prior to script execution
# The 'design' object is typically available in the OpenROAD Python environment

# --- Clock Definition and Propagation ---
# Create the clock signal on the specified input port with the given period and name
# The period is specified in nanoseconds, but Tcl 'create_clock' expects picoseconds. Convert ns to ps.
clock_period_ps = clock_period_ns * 1000
design.evalTclString(f"create_clock -period {clock_period_ps} [get_ports {clock_port_name}] -name {clock_net_name}")
# Propagate the defined clock signal throughout the design to enable timing analysis
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_net_name}}}]")
print(f"Clock '{clock_net_name}' created on port '{clock_port_name}' with period {clock_period_ns} ns and propagated.")

# --- Floorplanning ---
block = design.getBlock() # Get the current design block object
tech = design.getTech().getDB().getTech() # Get the technology database object

# Calculate required core area based on target utilization
dbu_per_micron = block.getDBUPerMicron() # Get DBU per micron from the block for conversions
total_std_cell_area_dbu2 = 0
# Iterate over all instances to sum up standard cell areas
for inst in block.getInsts():
    # Check if the instance is a standard cell (not a block/macro and is placeable by core placer)
    if not inst.getMaster().isBlock() and inst.getMaster().isCoreAutoPlaceable():
        total_std_cell_area_dbu2 += inst.getMaster().getWidth() * inst.getMaster().getHeight()

# Convert total standard cell area from DBU^2 to micron^2
total_std_cell_area_um2 = total_std_cell_area_dbu2 / (dbu_per_micron * dbu_per_micron)

# Calculate the target core area in micron^2 based on desired utilization
# Handle case where there are no standard cells
if total_std_cell_area_um2 > 0:
    target_core_area_um2 = total_std_cell_area_um2 / target_utilization
else:
    print("[WARNING] Total standard cell area is zero. Cannot calculate core area based on utilization.")
    target_core_area_um2 = 0 # Will use minimum size below

# Estimate core dimensions assuming aspect ratio similar to the block boundary
block_bbox = block.getBBox() # Get the bounding box of the current block
block_width_um = block.dbuToMicrons(block_bbox.getWidth()) # Block width in microns
block_height_um = block.dbuToMicrons(block_bbox.getHeight()) # Block height in microns

# Use block aspect ratio if valid, otherwise default to 1.0
if block_width_um > 0 and block_height_um > 0:
    block_aspect_ratio = block_height_um / block_width_um
else:
    print("[WARNING] Block boundary is zero size. Using default aspect ratio 1.0 for core area estimation.")
    block_aspect_ratio = 1.0
    # Provide a reasonable default size if block is empty/zero
    block_width_um = 200
    block_height_um = 200

# Estimate core width and height based on target area and block aspect ratio
if target_core_area_um2 > 0 and block_aspect_ratio > 0:
    estimated_core_width_um = (target_core_area_um2 / block_aspect_ratio)**0.5
    estimated_core_height_um = estimated_core_width_um * block_aspect_ratio
else:
    print("[WARNING] Target core area or block aspect ratio invalid. Using a default minimum size for core.")
    estimated_core_width_um = 100
    estimated_core_height_um = 100

# Convert estimated core dimensions back to DBU
core_width_dbu = design.micronToDBU(estimated_core_width_um)
core_height_dbu = design.micronToDBU(estimated_core_height_um)

# Find the standard cell site definition from existing rows or library
site = None
if block.getRows():
    site = block.getRows()[0].getSite()
elif tech.getLibs(): # Try to find a common site name like "CORE" in libraries
     for lib in tech.getLibs():
         site = lib.findSite("CORE")
         if site: break

if site:
    site_width = site.getWidth()
    site_height = site.getHeight()
    # Ensure core dimensions are multiples of the site size for legal placement
    core_width_dbu = (core_width_dbu // site_width) * site_width
    core_height_dbu = (core_height_dbu // site_height) * site_height
    print(f"Estimated core dimensions: {design.dbuToMicrons(core_width_dbu):.2f}um x {design.dbuToMicrons(core_height_dbu):.2f}um (aligned to site).")
else:
    print("[ERROR] Could not determine site size for floorplanning. Cannot create rows or initialize floorplan based on site.")
    # Cannot proceed with site-based floorplan initialization if site is missing
    site = None

# Set the core area based on calculated dimensions, centered within the potential die area
margin_dbu = design.micronToDBU(core_to_die_margin_um)
die_width_dbu = core_width_dbu + 2 * margin_dbu
die_height_dbu = core_height_dbu + 2 * margin_dbu

# Ensure a minimum die size if calculated dimensions are too small
min_die_dim_dbu = design.micronToDBU(50) # Example minimum size in DBU
die_width_dbu = max(die_width_dbu, min_die_dim_dbu)
die_height_dbu = max(die_height_dbu, min_die_dim_dbu)

# Recalculate core dimensions based on potentially adjusted die dimensions and margin
core_width_dbu = die_width_dbu - 2 * margin_dbu
core_height_dbu = die_height_dbu - 2 * margin_dbu
# Ensure core dimensions are still valid site multiples after adjustment
if site:
     core_width_dbu = (core_width_dbu // site_width) * site_width
     core_height_dbu = (core_height_dbu // site_height) * site_height
     # Adjust die size again if core size had to shrink due to site alignment
     die_width_dbu = core_width_dbu + 2 * margin_dbu
     die_height_dbu = core_height_dbu + 2 * margin_dbu

# Define die and core area rectangles in DBU coordinates (origin at 0,0)
die_area = odb.Rect(0, 0, die_width_dbu, die_height_dbu)
core_area = odb.Rect(margin_dbu, margin_dbu, margin_dbu + core_width_dbu, margin_dbu + core_height_dbu)

floorplan = design.getFloorplan() # Get the floorplan object

if site: # Proceed with floorplan initialization only if a valid site was found
    # Initialize floorplan with calculated die and core area and available site
    floorplan.initFloorplan(die_area, core_area, site)
    # Create placement rows based on the floorplan for standard cells
    floorplan.makeRows()
    # Create track patterns for routing based on the technology
    floorplan.makeTracks()
    print(f"Floorplan initialized with die area {design.dbuToMicrons(die_width_dbu):.2f}um x {design.dbuToMicrons(die_height_dbu):.2f}um and core area {design.dbuToMicrons(core_width_dbu):.2f}um x {design.dbuToMicrons(core_height_dbu):.2f}um (margin {core_to_die_margin_um}um).")
else:
    print("[ERROR] Floorplanning skipped due to inability to find site information.")

# --- IO Pin Placement ---
io_placer = design.getIOPlacer() # Get the IO placer object
io_params = io_placer.getParameters() # Get IO placer parameters

# Set minimum distance between pins (converted to DBU)
io_params.setMinDistance(design.micronToDBU(0)) # Set min distance (0 as per Example 1)
io_params.setMinDistanceInTracks(False) # Distance measured in DBU, not tracks
io_params.setCornerAvoidance(design.micronToDBU(0)) # No specific corner avoidance (0 as per Example 1)

# Find specified routing layers for IO placement by name
io_hor_layer = tech.findLayer(io_hor_layer_name)
io_ver_layer = tech.findLayer(io_ver_layer_name)

if io_hor_layer:
    # Add horizontal routing layer for IO pins
    io_placer.addHorLayer(io_hor_layer)
else:
    print(f"[WARNING] IO horizontal layer '{io_hor_layer_name}' not found.")

if io_ver_layer:
    # Add vertical routing layer for IO pins
    io_placer.addVerLayer(io_ver_layer)
else:
    print(f"[WARNING] IO vertical layer '{io_ver_layer_name}' not found.")

# Run the IO placer using annealing mode (True for random mode as in Example 1)
io_placer.runAnnealing(True)
print("IO pins placed.")

# --- Macro Placement ---
# Find all instances that are macro blocks (isBlock() returns True for instances of block masters)
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]
if len(macros) > 0:
    print(f"Found {len(macros)} macros. Running macro placement.")
    mpl = design.getMacroPlacer() # Get the macro placer object
    core = block.getCoreArea() # Get the core area from the floorplan

    # Define fence region for macros within the core area (converted to microns)
    # Macros will be constrained to be placed within this area
    fence_lx = block.dbuToMicrons(core.xMin())
    fence_ly = block.dbuToMicrons(core.yMin())
    fence_ux = block.dbuToMicrons(core.xMax())
    fence_uy = block.dbuToMicrons(core.yMax())

    # Configure and run macro placement
    mpl.place(
        num_threads = 64, # Number of threads for placement (example value)
        max_num_macro = len(macros), # Place all found macros
        min_num_macro = 0, # Minimum number of macros to place (0 means try to place all)
        max_num_inst = 0, # Do not place standard cells with macro placer
        min_num_inst = 0, # Minimum number of standard cells to place
        # Set halo around macros (converted to microns) - creates a keepout area around each macro
        # This helps in achieving minimum spacing requirements implicitly
        halo_width = macro_halo_um,
        halo_height = macro_halo_um,
        # Set fence region to core area (converted to microns) to constrain macros
        fence_lx = fence_lx,
        fence_ly = fence_ly,
        fence_ux = fence_ux,
        fence_uy = fence_uy,
        # Other parameters from Example 1 or documentation controlling placement quality and runtime
        tolerance = 0.1, # Controls convergence tolerance of the placer algorithm
        max_num_level = 2, # Maximum hierarchy levels to consider for macro clustering
        coarsening_ratio = 10.0, # Ratio for coarsening in hierarchical placement
        large_net_threshold = 50, # Threshold for identifying large nets
        signature_net_threshold = 50, # Threshold for signature nets
        area_weight = 0.1, # Weight for area objective function
        outline_weight = 100.0, # Weight for outline objective function
        wirelength_weight = 100.0, # Weight for wirelength objective function
        guidance_weight = 10.0, # Weight for guidance objective function
        fence_weight = 10.0, # Weight for fence constraint violation
        boundary_weight = 50.0, # Weight for boundary constraint violation
        notch_weight = 10.0, # Weight for notch minimization
        macro_blockage_weight = 10.0, # Weight for macro blockage effects on standard cells
        pin_access_th = 0.0, # Pin access threshold
        min_ar = 0.33, # Minimum aspect ratio for resulting clusters
        snap_layer = 4, # Example snap layer (M4) for macro pins/origins (by layer level)
        bus_planning_flag = False, # Enable/disable bus planning
        report_directory = "" # Directory for placement reports
    )
    print("Macros placed.")
else:
    print("No macros found. Skipping macro placement.")

# --- Standard Cell Placement (Global) ---
# Get the global placer object (Replace)
gpl = design.getReplace()
# Set target density for global placement (applies within the core area)
gpl.setTargetDensity(target_utilization)
# Enable routability driven mode to consider routing congestion during placement
gpl.setRoutabilityDrivenMode(True)
# Use uniform target density across the core area
gpl.setUniformTargetDensityMode(True)
# Run initial quadratic placement
gpl.doInitialPlace(threads = 4) # Example: Use 4 threads for multi-threading
# Run Nesterov-based global placement for refinement
gpl.doNesterovPlace(threads = 4) # Example: Use 4 threads
# Reset placer state if needed for subsequent steps
gpl.reset()
print("Global placement finished.")

# --- Standard Cell Placement (Detailed) ---
# Get the detailed placer object (Opendp)
dp = design.getOpendp()

# Remove filler cells before detailed placement if any were previously inserted
# This allows standard cells to move into filler locations during optimization
dp.removeFillers()

# Convert max displacement from microns to DBU
dp_max_disp_x_dbu = design.micronToDBU(dp_max_disp_x_um)
dp_max_disp_y_dbu = design.micronToDBU(dp_max_disp_y_um)

# Run detailed placement with specified maximum displacement allowances
dp.detailedPlacement(dp_max_disp_x_dbu, dp_max_disp_y_dbu, "", False) # "" for corners, False for not using defects
print("Detailed placement finished.")

# --- Clock Tree Synthesis (CTS) ---
# Set unit resistance and capacitance values for clock and signal wires using TCL commands
design.evalTclString(f"set_wire_rc -clock -resistance {wire_rc_resistance} -capacitance {wire_rc_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {wire_rc_resistance} -capacitance {wire_rc_capacitance}")
print(f"Set wire RC values (R={wire_rc_resistance}, C={wire_rc_capacitance}).")

# Get CTS object
cts = design.getTritonCts()
# Set the clock net to synthesize based on its name
cts.setClockNets(clock_net_name)
# Set the list of available clock buffer cells to use in the tree
cts.setBufferList(cts_buffer_name)
# Set the cell to use as the root buffer (connected to the clock source)
cts.setRootBuffer(cts_buffer_name)
# Set the cell to use as sink buffers (inserted near flip-flop clock pins)
cts.setSinkBuffer(cts_buffer_name)

# Run the CTS engine
cts.runTritonCts()
print(f"Clock Tree Synthesis finished for clock '{clock_net_name}'.")

# --- Power Delivery Network (PDN) Generation ---
# Get PDN generator object
pdngen = design.getPdnGen()

# Find or create VDD and VSS nets in the block
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

# Create VDD/VSS nets if they don't exist and mark them as special (not routed by signal router)
if VDD_net is None:
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSigType("POWER")
    VDD_net.setSpecial()
    print("Created VDD net.")
if VSS_net is None:
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSigType("GROUND")
    VSS_net.setSpecial()
    print("Created VSS net.")

# Connect power and ground pins of instances to the global VDD/VSS nets
# This ensures standard cells and macros are connected to the PDN nets after placement
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VDD$", net=VDD_net, do_connect=True)
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VSS$", net=VSS_net, do_connect=True)
block.globalConnect()
print("Global power/ground connections made.")

# Set the core power domain, associating VDD as primary power and VSS as primary ground
core_domain = pdngen.findDomain("Core") # Try to find the core domain if already defined
if core_domain is None:
     pdngen.setCoreDomain(power = VDD_net, switched_power = None, ground = VSS_net, secondary = [])
     core_domain = pdngen.findDomain("Core") # Get the newly set core domain
     print("Core power domain set.")
else:
     print("Core domain already exists.")


# Define via cut pitch for connections between layers (converted to DBU)
pdn_via_cut_pitch_dbu_x = design.micronToDBU(pdn_via_pitch_um)
pdn_via_cut_pitch_dbu_y = design.micronToDBU(pdn_via_pitch_um)
pdn_cut_pitch = [pdn_via_cut_pitch_dbu_x, pdn_via_cut_pitch_dbu_y]

# Define offset for straps/rings (converted to DBU)
pdn_offset_dbu = design.micronToDBU(pdn_offset_um)

# Get necessary metal layers from the technology database by name
m1 = tech.findLayer("M1")
m4 = tech.findLayer("M4")
m5 = tech.findLayer("M5")
m6 = tech.findLayer("M6")
m7 = tech.findLayer("M7")
m8 = tech.findLayer("M8")

# Check if required layers are found for core PDN
required_layers_core = { "M1":m1, "M4":m4, "M7":m7, "M8":m8 }
core_layers_ok = all(required_layers_core.values())
if not core_layers_ok:
    missing = [name for name, layer in required_layers_core.items() if not layer]
    print(f"[ERROR] Missing required core PDN layers: {missing}. Cannot build core PDN.")

# Create and configure Core PDN if layers and domain are OK
core_grid = None
if core_layers_ok and core_domain is not None:
    # Create the main core grid structure within the Core domain
    pdngen.makeCoreGrid(domain = core_domain,
                        name = "core_grid", # Name for the core grid structure
                        starts_with = pdn.GROUND, # Start pattern for straps (e.g., start with VSS strap)
                        pin_layers = [], # Layers to connect to from standard cells (empty means infer based on tech)
                        generate_obstructions = [], # Layers to generate routing obstructions on the grid
                        powercell = None, powercontrol = None, powercontrolnetwork = "STAR") # PDN type

    core_grid = pdngen.findGrid("core_grid") # Get the created core grid object

    if core_grid is None:
        print("[ERROR] Core grid 'core_grid' not found after creation. Skipping core PDN straps, rings, and connects.")
        core_layers_ok = False # Prevent strap/connect creation even if layers OK

if core_layers_ok and core_grid is not None:
    # --- Add core power straps ---
    # M1 Followpin straps following standard cell power pins on the lowest metal layer
    pdngen.makeFollowpin(grid = core_grid,
                         layer = m1,
                         width = design.micronToDBU(pdn_core_grid_m1_width_um),
                         extend = pdn.CORE) # Extend followpins within the core area

    # M4 Straps - part of the core grid mesh
    pdngen.makeStrap(grid = core_grid,
                     layer = m4,
                     width = design.micronToDBU(pdn_core_grid_m4_width_um),
                     spacing = design.micronToDBU(pdn_core_grid_m4_spacing_um),
                     pitch = design.micronToDBU(pdn_core_grid_m4_pitch_um),
                     offset = pdn_offset_dbu,
                     number_of_straps = 0, # Auto-calculate number of straps based on pitch and area
                     snap = False, # Do not snap strap start/end points to grid explicitly
                     starts_with = pdn.GRID, # Pattern starts relative to the grid boundary
                     extend = pdn.CORE, # Extend straps within the core area
                     nets = []) # Apply to all nets in the grid (VDD/VSS)

    # M7 Straps - part of the core grid mesh
    pdngen.makeStrap(grid = core_grid,
                     layer = m7,
                     width = design.micronToDBU(pdn_core_grid_m7_width_um),
                     spacing = design.micronToDBU(pdn_core_grid_m7_spacing_um),
                     pitch = design.micronToDBU(pdn_core_grid_m7_pitch_um),
                     offset = pdn_offset_dbu,
                     number_of_straps = 0,
                     snap = False,
                     starts_with = pdn.GRID,
                     extend = pdn.CORE,
                     nets = [])

    # M8 Straps - part of the core grid mesh
    pdngen.makeStrap(grid = core_grid,
                     layer = m8,
                     width = design.micronToDBU(pdn_core_grid_m8_width_um),
                     spacing = design.micronToDBU(pdn_core_grid_m8_spacing_um),
                     pitch = design.micronToDBU(pdn_core_grid_m8_pitch_um),
                     offset = pdn_offset_dbu,
                     number_of_straps = 0,
                     snap = False,
                     starts_with = pdn.GRID,
                     extend = pdn.CORE,
                     nets = [])

    # --- Add core power rings ---
    # Create power rings on M7 and M8 around the core area boundary
    pdngen.makeRing(grid = core_grid,
                    layer0 = m7, width0 = design.micronToDBU(pdn_ring_m7_width_um), spacing0 = design.micronToDBU(pdn_ring_m7_spacing_um),
                    layer1 = m8, width1 = design.micronToDBU(pdn_ring_m8_width_um), spacing1 = design.micronToDBU(pdn_ring_m8_spacing_um),
                    starts_with = pdn.GRID, # Ring pattern starts relative to the grid boundary
                    offset = [pdn_offset_dbu] * 4, # [left, bottom, right, top] offset from boundary
                    pad_offset = [0] * 4, # Offset for connections to pads (if any)
                    extend = False, # Rings typically do not extend beyond the defined boundary
                    pad_pin_layers = [], # Layers for pad pin connections
                    nets = []) # Apply to all nets in the grid (VDD/VSS)

    # --- Add core via connections ---
    # Connect straps between layers using vias with specified via pitch
    # Connect M1 (followpins) to M4 (straps)
    pdngen.makeConnect(grid = core_grid, layer0 = m1, layer1 = m4,
                       cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1],
                       vias = [], techvias = [], max_rows = 0, max_columns = 0,
                       ongrid = [], split_cuts = dict(), dont_use_vias = "")
    # Connect M4 to M7
    pdngen.makeConnect(grid = core_grid, layer0 = m4, layer1 = m7,
                       cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1],
                       vias = [], techvias = [], max_rows = 0, max_columns = 0,
                       ongrid = [], split_cuts = dict(), dont_use_vias = "")
    # Connect M7 to M8
    pdngen.makeConnect(grid = core_grid, layer0 = m7, layer1 = m8,
                       cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1],
                       vias = [], techvias = [], max_rows = 0, max_columns = 0,
                       ongrid = [], split_cuts = dict(), dont_use_vias = "")
    print("Core PDN straps, rings, and vias configured.")
else:
    print("Core PDN configuration skipped due to errors.")


# --- Create PDN for Macro Blocks (if macros exist) ---
# Check if required layers are found for macro PDN
required_layers_macro = { "M5":m5, "M6":m6 }
macro_layers_ok = all(required_layers_macro.values())

if len(macros) > 0:
    if not macro_layers_ok:
        missing = [name for name, layer in required_layers_macro.items() if not layer]
        print(f"[WARNING] Missing required macro PDN layers: {missing}. Skipping macro PDN generation.")
    elif core_domain is None:
        print("[ERROR] Core domain not found. Cannot create macro instance grids. Skipping macro PDN generation.")
        macro_layers_ok = False # Prevent macro PDN generation if domain is missing
    elif core_grid is None:
        # Note: Macro PDN can still be built but might lack proper connection to the core grid
        print("[WARNING] Core grid not found. Macro PDN might not connect correctly to core PDN. Proceeding with macro PDN creation.")


    if len(macros) > 0 and macro_layers_ok and core_domain is not None:
        print("Creating PDN for macros.")
        # Define halo around macros for PDN exclusion/extension (in DBU) - reuse placement halo value
        macro_halo_dbu = design.micronToDBU(macro_halo_um)
        pdn_macro_halo = [macro_halo_dbu] * 4 # [left, bottom, right, top] halo size

        # Create PDN structures for each individual macro instance
        for i, macro in enumerate(macros):
            # Create a separate instance grid associated with the core domain for each macro
            # This grid will be localized to the macro instance area including the halo
            pdngen.makeInstanceGrid(domain = core_domain,
                                    name = f"macro_grid_{macro.getName()}", # Use macro name for unique grid name
                                    starts_with = pdn.GROUND, # Start pattern for macro straps
                                    inst = macro, # Associate grid with this instance
                                    halo = pdn_macro_halo, # Apply halo/keepout area around the macro instance
                                    pg_pins_to_boundary = True, # Connect macro PG pins to the macro instance grid boundary
                                    default_grid = False, # This is an instance-specific grid
                                    generate_obstructions = [], # Layers to obstruct within the macro
                                    is_bump = False) # Not a bump pad grid

            macro_grid = pdngen.findGrid(f"macro_grid_{macro.getName()}") # Get the created instance grid object

            if macro_grid is None:
                 print(f"[ERROR] Macro instance grid 'macro_grid_{macro.getName()}' not found after creation. Skipping PDN structures for this macro.")
                 continue # Skip to next macro

            # --- Add macro power straps ---
            # M5 Straps for macro instance grid
            pdngen.makeStrap(grid = macro_grid,
                             layer = m5,
                             width = design.micronToDBU(pdn_macro_grid_m5_width_um),
                             spacing = design.micronToDBU(pdn_macro_grid_m5_spacing_um),
                             pitch = design.micronToDBU(pdn_macro_grid_m5_pitch_um),
                             offset = pdn_offset_dbu,
                             number_of_straps = 0, # Auto-calculate number
                             snap = True, # Snap macro straps to grid
                             starts_with = pdn.GRID, # Pattern starts relative to the macro grid boundary
                             extend = pdn.CORE, # Extend within the macro's context relative to core (connects to outer grid)
                             nets = []) # Apply to VDD/VSS nets in the grid

            # M6 Straps for macro instance grid
            pdngen.makeStrap(grid = macro_grid,
                             layer = m6,
                             width = design.micronToDBU(pdn_macro_grid_m6_width_um),
                             spacing = design.micronToDBU(pdn_macro_grid_m6_spacing_um),
                             pitch = design.micronToDBU(pdn_macro_grid_m6_pitch_um),
                             offset = pdn_offset_dbu,
                             number_of_straps = 0,
                             snap = True,
                             starts_with = pdn.GRID,
                             extend = pdn.CORE,
                             nets = [])

            # --- Add macro power rings ---
            # Create rings on M5 and M6 around the macro instance area (within the halo)
            pdngen.makeRing(grid = macro_grid,
                            layer0 = m5, width0 = design.micronToDBU(pdn_macro_ring_m5_width_um), spacing0 = design.micronToDBU(pdn_macro_ring_m5_spacing_um),
                            layer1 = m6, width1 = design.micronToDBU(pdn_macro_ring_m6_width_um), spacing1 = design.micronToDBU(pdn_macro_ring_m6_spacing_um),
                            starts_with = pdn.GRID, # Ring pattern starts relative to the macro grid boundary
                            offset = [pdn_offset_dbu] * 4, # [left, bottom, right, top] offset from boundary
                            pad_offset = [0] * 4, # Offset for connections to pads (not applicable here)
                            extend = False, # Rings typically do not extend beyond the defined boundary
                            pad_pin_layers = [], # Layers for pad pin connections
                            nets = []) # Apply to VDD/VSS nets in the grid

            # --- Add macro via connections ---
            # Connect macro grid layers (M5, M6) and connect to surrounding core grid (M4, M7)
            # Ensure layer order is correct for via generation (lower layer first)
            if m4 and m5: # Connect M4 (core grid) to M5 (macro grid)
                 pdngen.makeConnect(grid = macro_grid, layer0 = m4, layer1 = m5,
                                   cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1],
                                   vias = [], techvias = [], max_rows = 0, max_columns = 0,
                                   ongrid = [], split_cuts = dict(), dont_use_vias = "")
            if m5 and m6: # Connect M5 to M6 within the macro grid
                 pdngen.makeConnect(grid = macro_grid, layer0 = m5, layer1 = m6,
                                   cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1],
                                   vias = [], techvias = [], max_rows = 0, max_columns = 0,
                                   ongrid = [], split_cuts = dict(), dont_use_vias = "")
            if m6 and m7: # Connect M6 (macro grid) to M7 (core grid)
                 pdngen.makeConnect(grid = macro_grid, layer0 = m6, layer1 = m7,
                                   cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1],
                                   vias = [], techvias = [], max_rows = 0, max_columns = 0,
                                   ongrid = [], split_cuts = dict(), dont_use_vias = "")
        print("Macro PDN straps, rings, and vias configured.")
    else:
        print("Macro PDN configuration skipped due to errors or no macros found.")
else:
    print("No macros found. Skipping macro PDN generation.")


# --- Generate the final power delivery network (if any grid was configured successfully) ---
if core_grid is not None or (len(macros) > 0 and macro_layers_ok and core_domain is not None):
    pdngen.checkSetup()  # Verify PDN configuration before building
    pdngen.buildGrids(False)  # Build the PDN geometry based on configured grids (False = do not automatically create pins, relying on globalConnect)
    pdngen.writeToDb(True)  # Write the generated PDN shapes to the design database (True = commit changes)
    pdngen.resetShapes() # Clear temporary shapes used during generation
    print("Power Delivery Network generated.")
else:
    print("PDN generation skipped.")

# --- Filler Cell Placement ---
# Find filler cell masters in the technology library
db = ord.get_db() # Get the database object
filler_masters = list()
if tech:
    for lib in tech.getLibs():
        for master in lib.getMasters():
            # Identify filler cells, typically marked as CORE_SPACER or by naming convention
            # Check for CORE_SPACER type or common naming prefixes
            if master.getType() == "CORE_SPACER" or master.getName().startswith("FILLCELL_") or master.getName().startswith("SPACER_"):
                 # Optionally add checks for standard cell height compatibility if multiple types exist
                 if site and master.getHeight() > 0 and (master.getHeight() % site.getHeight()) == 0: # Check if height is a multiple of site height
                     filler_masters.append(master)
                 elif site is None: # If site isn't found yet, just add based on type/name (less safe)
                     filler_masters.append(master)


if len(filler_masters) == 0:
    print("[WARNING] No suitable filler cells found in libraries with type CORE_SPACER or prefix FILLCELL_/SPACER_. Skipping filler placement.")
elif site is None:
     print("[ERROR] Site information not available. Cannot perform filler placement. Skipping filler placement.")
else:
    print(f"Found {len(filler_masters)} filler masters. Running filler placement.")
    # Get the detailed placer object (already got it as dp)
    # Insert filler cells into empty spaces in standard cell rows
    dp.fillerPlacement(filler_masters = filler_masters,
                       prefix = "FILLCELL_", # Prefix for new filler instance names
                       verbose = False) # Reduced verbosity
    print("Filler cells placed.")

# --- Global Routing ---
grt = design.getGlobalRouter() # Get the global router object

# Find routing layers by name
min_route_layer = tech.findLayer(global_route_min_layer_name)
max_route_layer = tech.findLayer(global_route_max_layer_name)

if not min_route_layer or not max_route_layer:
    print(f"[ERROR] Global routing layers '{global_route_min_layer_name}' or '{global_route_max_layer_name}' not found. Skipping global routing.")
else:
    # Set minimum and maximum routing layers for signal nets
    grt.setMinRoutingLayer(min_route_layer.getRoutingLevel())
    grt.setMaxRoutingLayer(max_route_layer.getRoutingLevel())
    # Set minimum and maximum routing layers for clock nets (assuming same range unless specified)
    grt.setMinLayerForClock(min_route_layer.getRoutingLevel())
    grt.setMaxLayerForClock(max_route_layer.getRoutingLevel())

    # Configure global router parameters (example values from Example 1)
    grt.setAdjustment(0.5) # Set congestion adjustment value (0.5 = 50% adjustment)
    grt.setVerbose(True) # Enable verbose output

    # The prompt mentioned global router iterations (10), but there is no standard API method
    # to set a fixed number of iterations for globalRoute in the examples provided.
    # The tool will likely run a default number of iterations or until convergence.
    print("Configured global router. Note: Explicit iteration count not set via available API.")

    # Run global routing
    grt.globalRoute(True) # True enables rip-up and reroute iterations
    print(f"Global routing finished using layers {global_route_min_layer_name} to {global_route_max_layer_name}.")

# --- Detailed Routing ---
drter = design.getTritonRoute() # Get the detailed router object

# Get detailed router parameters object
dr_params = drt.ParamStruct()

# Set detailed routing layer range by name
dr_min_layer = tech.findLayer(detailed_route_min_layer_name)
dr_max_layer = tech.findLayer(detailed_route_max_layer_name)

if not dr_min_layer or not dr_max_layer:
     print(f"[ERROR] Detailed routing layers '{detailed_route_min_layer_name}' or '{detailed_route_max_layer_name}' not found. Skipping detailed routing.")
else:
    # Set the bottom and top routing layers by name
    dr_params.bottomRoutingLayer = detailed_route_min_layer_name
    dr_params.topRoutingLayer = detailed_route_max_layer_name

    # Set other detailed router parameters (from Example 1 defaults or common usage)
    dr_params.outputMazeFile = "" # Optional: output maze file path
    dr_params.outputDrcFile = "" # Optional: output DRC report file path (e.g., "droute.drc")
    dr_params.outputCmapFile = "" # Optional: output cmap file path
    dr_params.outputGuideCoverageFile = "" # Optional: output guide coverage file path
    dr_params.dbProcessNode = "" # Optional: specify DB process node name
    dr_params.enableViaGen = True # Enable via generation during detailed routing
    dr_params.drouteEndIter = 1 # Number of detailed routing iterations (usually 1-3)
    dr_params.viaInPinBottomLayer = "" # Optional: Bottom layer name for via-in-pin
    dr_params.viaInPinTopLayer = "" # Optional: Top layer name for via-in-pin
    dr_params.orSeed = -1 # Random seed for routing (-1 uses time)
    dr_params.orK = 0 # Optional: Routing parameter k
    dr_params.verbose = 1 # Verbosity level (0-3)
    dr_params.cleanPatches = True # Clean redundant routing patches after routing
    dr_params.doPa = True # Perform post-route pin access optimization
    dr_params.singleStepDR = False # Do not run in single-step mode
    dr_params.minAccessPoints = 1 # Minimum number of pin access points to ensure connectivity
    dr_params.saveGuideUpdates = False # Do not save intermediate guide updates

    # Apply configured parameters to the detailed router
    drter.setParams(dr_params)

    # Run detailed routing
    drter.main()
    print(f"Detailed routing finished using layers {detailed_route_min_layer_name} to {detailed_route_max_layer_name}.")

# --- IR Drop Analysis ---
# The OpenROAD Python API for IR Drop analysis is not explicitly provided in the examples or common usage.
# IR Drop analysis typically requires loading a power model, specifying the analysis type (static/dynamic),
# and target layers/nets. This step might be performed by a separate tool or requires specific
# setup not covered by the standard placement/routing flow API calls shown.
# A TCL command like "analyze_irdrop ..." is often used within the OpenROAD environment.
# Placeholder comment indicating where the analysis would conceptually occur if the API were available.
# Assuming a command exists, it would look something like:
# design.evalTclString(f"analyze_irdrop -power_net {VDD_net.getName()} -ground_net {VSS_net.getName()} -layers {{{ir_drop_layer_name}}} -method static")
print(f"[INFO] IR Drop analysis requested on layer {ir_drop_layer_name}. Direct Python API call not available in provided examples or common flow. Skipping analysis.")

# --- Save Output DEF ---
# Write the final design database state to a DEF file, including floorplan, placement, and routing information
design.writeDef(output_def_file)
print(f"Final design saved to {output_def_file}")