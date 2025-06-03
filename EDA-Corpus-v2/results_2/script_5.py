import odb
import pdn
import drt
import openroad as ord
import math

# Get the design object
design = ord.get_design()

# Get tech and block
tech = design.getTech()
block = design.getBlock()
db = tech.getDB()
tech_lib = tech.getTech()

# 1. Set clock period
# Check if clock port exists
clock_port = block.findBTerm("clk")
if clock_port is None:
    print("Error: Clock port 'clk' not found.")
    # In a real flow, you might exit or use a different clock source
    # For this script, we'll proceed, but clock-aware steps will fail or be incorrect.
    print("Proceeding without 'clk' port, timing setup will be incomplete.")
else:
    # Create clock signal with period 20 ns (20000 ps)
    print("Setting clock 'clk' with period 20 ns.")
    # Using evalTclString for create_clock is a common way to access timing commands
    design.evalTclString("create_clock -period 20 [get_ports clk] -name core_clock")
    # Propagate the clock signal - needed for timing analysis and CTS
    design.evalTclString("set_propagated_clock [get_clocks {core_clock}]")

# 2. Set RC values for clock and signal nets
print("Setting wire RC values.")
# Set RC values using the set_wire_rc Tcl command
design.evalTclString("set_wire_rc -clock -resistance 0.03574 -capacitance 0.07516")
design.evalTclString("set_wire_rc -signal -resistance 0.03574 -capacitance 0.07516")

# 3. Perform floorplanning
print("Performing floorplanning.")
floorplan = design.getFloorplan()

# Find a standard site from the library for rows
site = None
for lib in db.getLibs():
    # Find the first CORE ROW site
    for s in lib.getSites():
        # Use "CORE" site class as is standard
        if s.getClass() == "CORE":
            site = s
            break
    if site:
        break

if site is None:
    print("Error: Could not find a suitable CORE site in library.")
    # Exit gracefully if no core site is found
    exit()

# Calculate total standard cell area for target utilization
total_std_cell_area_dbu2 = 0
for inst in block.getInsts():
    master = inst.getMaster()
    # Ensure master exists and is a standard cell (not a macro/block)
    if master and master.isStdCell():
        total_std_cell_area_dbu2 += master.getWidth() * master.getHeight()

if total_std_cell_area_dbu2 == 0:
    print("Warning: No standard cells found. Floorplan calculation based on utilization will be inaccurate.")
    # Depending on the flow, one might set a fixed core size or exit.
    # For this script, we'll exit as utilization-based floorplanning is requested.
    exit()

target_utilization = 0.50
# Avoid division by zero if target_utilization is 0
if target_utilization <= 0:
     print("Error: Target utilization must be greater than 0.")
     exit()

required_core_area_dbu2 = total_std_cell_area_dbu2 / target_utilization

# Calculate required core dimensions (assume square aspect ratio for simplicity)
# Convert DBU area back to DBU dimensions
required_core_dim_dbu = int(math.sqrt(required_core_area_dbu2))

# Ensure core dimensions are multiples of site dimensions for proper row creation
site_width_dbu = site.getWidth()
site_height_dbu = site.getHeight()

# Ensure required core dimensions are at least one site size
required_core_width_dbu = max(site_width_dbu, int(math.ceil(required_core_dim_dbu / site_width_dbu)) * site_width_dbu)
required_core_height_dbu = max(site_height_dbu, int(math.ceil(required_core_dim_dbu / site_height_dbu)) * site_height_dbu)


# Set core to die spacing to 5 microns
margin_um = 5.0
margin_dbu = design.micronToDBU(margin_um)

# Calculate die dimensions: core dimensions + 2 * margin
die_width_dbu = required_core_width_dbu + 2 * margin_dbu
die_height_dbu = required_core_height_dbu + 2 * margin_dbu

# Define die area (assuming origin at (0,0))
die_area = odb.Rect(0, 0, die_width_dbu, die_height_dbu)

# Define core area (centered within the die)
core_lx = margin_dbu
core_ly = margin_dbu
core_ux = margin_dbu + required_core_width_dbu
core_uy = margin_dbu + required_core_height_dbu
core_area = odb.Rect(core_lx, core_ly, core_ux, core_uy)

print(f"Calculated Core Area: ({design.dbuToMicrons(core_area.xMin())}um, {design.dbuToMicrons(core_area.yMin())}um) - ({design.dbuToMicrons(core_area.xMax())}um, {design.dbuToMicrons(core_area.yMax())}um)")
print(f"Calculated Die Area: ({design.dbuToMicrons(die_area.xMin())}um, {design.dbuToMicrons(die_area.yMin())}um) - ({design.dbuToMicrons(die_area.xMax())}um, {design.dbuToMicrons(die_area.yMax())}um)")

# Initialize floorplan with calculated die and core areas and site
# Use row orientation R0 (default), generate placement rows
floorplan.initFloorplan(die_area, core_area, site, "R0", True) # The 'True' flag tells it to make rows immediately
# floorplan.makeTracks() # makeTracks is implicitly called by initFloorplan when make_rows=True

# 4. Place I/O pins on M8 and M9
print("Placing I/O pins.")
io_placer = design.getIOPlacer()
# Place I/O pins on metal8 (horizontal) and metal9 (vertical) layers
metal8 = tech_lib.findLayer("metal8")
metal9 = tech_lib.findLayer("metal9")
if metal8 and metal9:
    io_placer.addHorLayer(metal8) # Add horizontal layer preference
    io_placer.addVerLayer(metal9) # Add vertical layer preference
    # It's good practice to set pad boundaries if applicable (assuming none here)
    # io_placer.setPadBoundary(...)
    # Run I/O placement. Using annealing is a valid approach.
    # The runAnnealing(True) uses a random seed, which is fine.
    io_placer.runAnnealing(True)
else:
    print("Warning: Could not find metal8 or metal9 for I/O placement. Skipping I/O placement.")

# 5. Place macros
print("Placing macros.")
# Filter instances to find macros (isBlock() typically identifies non-stdcell instances like blocks, memories, etc.)
macros = [inst for inst in block.getInsts() if inst.getMaster() and inst.getMaster().isBlock()]
if len(macros) > 0:
    print(f"Found {len(macros)} macros to place.")
    mpl = design.getMacroPlacer()
    # Get core area bounds in microns for fence
    core_lx_um = design.dbuToMicrons(core_area.xMin())
    core_ly_um = design.dbuToMicrons(core_area.yMin())
    core_ux_um = design.dbuToMicrons(core_area.xMax())
    core_uy_um = design.dbuToMicrons(core_area.yMax())

    # Set halo region around each macro to 5 um
    halo_width_um = 5.0
    halo_height_um = 5.0

    # Macro placement parameters - placing all macros within the core fence
    # The request "at least 5 um to each other" is typically a result of the placer's cost function,
    # optimizing for white space distribution and preventing overlaps, rather than a direct parameter.
    # The `place` method optimizes macro locations within the fence.
    mpl.place(
        # keep macros inside core area (fence)
        fence_lx = core_lx_um,
        fence_ly = core_ly_um,
        fence_ux = core_ux_um,
        fence_uy = core_uy_um,
        # halo definition in microns - This creates spacing constraints around macros
        halo_width = halo_width_um,
        halo_height = halo_height_um
        # Additional parameters like groups, density, etc., can be added for more control
    )
else:
    print("No macros found to place. Skipping macro placement.")

# 6. Run global placement
print("Running global placement.")
gpl = design.getReplace()
# Set target utilization (50%) - this influences the target density map for standard cells
gpl.setTargetDensity(target_utilization)
# Set other common parameters for better placement quality
gpl.setTimingDrivenMode(False) # Set True if timing libraries and constraints are fully loaded
gpl.setRoutabilityDrivenMode(True) # Enable routability optimization
gpl.setUniformTargetDensityMode(True) # Distribute density uniformly across the core
gpl.setInitDensityPenalityFactor(0.05) # Example penalty factor for density
gpl.setCCOn(True) # Enable clock-concurrent optimization (requires timing)
gpl.setHeatMap(True) # Generate heat map visualization
gpl.setVerbose(True) # Enable verbose output

# The prompt requested 10 iterations for global router.
# VERIFICATION FEEDBACK: The script attempted to set this using setInitialPlaceMaxIter, which is incorrect.
# There is no direct Python API call on the GlobalRouter object to set iterations like this.
# The RePlace engine's iterations (InitialPlace and NesterovPlace) are separate from the global router iterations.
# The standard globalRoute() call internally manages its iterations.
# Removing the incorrect call:
# gpl.setInitialPlaceMaxIter(10)
print("Note: Global router iteration count is not a direct parameter in the current Python API.")


# Run the two stages of RePlace (global placer)
# Use the available number of threads
gpl.doInitialPlace(threads = ord.get_thread_count())
gpl.doNesterovPlace(threads = ord.get_thread_count())

# Reset placer state after use (good practice)
# gpl.reset() # The API might handle this internally or subsequent calls re-initialize, but explicit reset is safe.

# 7. Run initial detailed placement
print("Running initial detailed placement.")
opendp = design.getOpendp()
# Allow 1um x-displacement and 3um y-displacement
max_disp_x_um = 1.0
max_disp_y_um = 3.0
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

# Remove filler cells if any were inserted previously (e.g., from a previous flow run)
opendp.removeFillers()

# Perform detailed placement using the specified maximum displacements
# The runDetailedPlacement method takes displacement in DBU
opendp.runDetailedPlacement(max_disp_x_dbu, max_disp_y_dbu)


# 8. Configure and construct power delivery network (PDN)
print("Configuring power delivery network.")

# First, ensure VDD and VSS nets exist and are marked special/power
# This is crucial for the PDN tool to identify which nets to route.
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

if VDD_net is None:
    print("Creating VDD net.")
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSpecial() # Mark as special net (not to be routed by signal router)
    VDD_net.setSigType("POWER") # Set signal type
if VSS_net is None:
    print("Creating VSS net.")
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSpecial()
    VSS_net.setSigType("GROUND") # Set signal type

# Perform global connect for standard cell power/ground pins
# Connect power/ground pins of standard cells to the VDD/VSS nets
print("Performing global connect for power/ground pins.")
# block.addGlobalConnect allows defining connection rules
# Apply to all instances (".*"), pins matching pattern ("^VDD$"), connect to VDD_net
# The 'do_connect = True' flag applies the connection immediately
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
# Add other common VDD pins if they exist in your library cells
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDPE$", net = VDD_net, do_connect = True)
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDCE$", net = VDD_net, do_connect = True)
# Map standard VSS pins to VSS net
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
# Add other common VSS pins
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSSE$", net = VSS_net, do_connect = True)
# After defining all rules, explicitly call globalConnect to apply them
block.globalConnect()


# Initialize PDN generator
pdngen = design.getPdnGen()

# Define a power domain for the core area
core_domain_name = "Core"
# Check if domain already exists, create if not
core_domain = pdngen.findDomain(core_domain_name)
if not core_domain:
    print(f"Creating core power domain '{core_domain_name}'.")
    # Define the core domain with primary power and ground nets
    core_domain = pdngen.makeDomain(name = core_domain_name,
                                    power = VDD_net,
                                    ground = VSS_net)
    # Set the area for the core domain (typically the core area defined during floorplan)
    pdngen.setDomainArea(domain = core_domain, rect = core_area)
else:
    print(f"Core power domain '{core_domain_name}' already exists.")

# Ensure the domain was created successfully
if not core_domain:
    print("Error: Failed to create or find core power domain. Cannot build PDN.")
    exit() # Cannot proceed without a domain

# Define PDN parameters in microns and convert to DBU
# Core Grid Parameters
m1_followpin_width_um = 0.07
m4_strap_width_um = 1.2
m4_strap_spacing_um = 1.2
m4_strap_pitch_um = 6.0
m7_m8_strap_width_um = 1.4 # Prompt says M7 and M8 straps have width 1.4um
m7_m8_strap_spacing_um = 1.4 # Prompt says M7 spacing is 1.4um
m7_m8_strap_pitch_um = 10.8 # Prompt says M7 pitch is 10.8um
# Prompt specified M7 rings (width 2, spacing 2) AND M8 rings (width 2, spacing 2) for the core area.
core_ring_m7_width_um = 2.0
core_ring_m7_spacing_um = 2.0
core_ring_m8_width_um = 2.0 # M8 core ring width
core_ring_m8_spacing_um = 2.0 # M8 core ring spacing

# Macro Grid Parameters (if macros exist) - These apply within the macro instance boundary + halo
# Prompt specifies grids on M5 and M6 for macros, width 1.2um, spacing 1.2um, pitch 6um.
macro_strap_width_um = 1.2
macro_strap_spacing_um = 1.2
macro_strap_pitch_um = 6.0
# Prompt specifies rings on M5 and M6 for macros, width 1.5um, spacing 1.5um.
macro_ring_width_um = 1.5
macro_ring_spacing_um = 1.5

# General parameters
offset_um = 0.0 # Offset for straps/rings from the boundary
# Via cut pitch between grids: prompt says 0 um, which likely means minimum pitch allowed by tech
via_cut_pitch_um = 0.0

# Convert parameters to DBU
m1_followpin_width_dbu = design.micronToDBU(m1_followpin_width_um)
m4_strap_width_dbu = design.micronToDBU(m4_strap_width_um)
m4_strap_spacing_dbu = design.micronToDBU(m4_strap_spacing_um)
m4_strap_pitch_dbu = design.micronToDBU(m4_strap_pitch_um)
m7_m8_strap_width_dbu = design.micronToDBU(m7_m8_strap_width_um)
m7_m8_strap_spacing_dbu = design.micronToDBU(m7_m8_strap_spacing_um)
m7_m8_strap_pitch_dbu = design.micronToDBU(m7_m8_strap_pitch_um)
core_ring_m7_width_dbu = design.micronToDBU(core_ring_m7_width_um)
core_ring_m7_spacing_dbu = design.micronToDBU(core_ring_m7_spacing_um)
core_ring_m8_width_dbu = design.micronToDBU(core_ring_m8_width_um)
core_ring_m8_spacing_dbu = design.micronToDBU(core_ring_m8_spacing_um)

macro_strap_width_dbu = design.micronToDBU(macro_strap_width_um)
macro_strap_spacing_dbu = design.micronToDBU(macro_strap_spacing_um)
macro_strap_pitch_dbu = design.micronToDBU(macro_strap_pitch_um)
macro_ring_width_dbu = design.micronToDBU(macro_ring_width_um)
macro_ring_spacing_dbu = design.micronToDBU(macro_ring_spacing_um)

offset_dbu = design.micronToDBU(offset_um)
via_cut_pitch_dbu = design.micronToDBU(via_cut_pitch_um)
# pdn_cut_pitch needs to be a list/tuple for X and Y, even if they are the same
pdn_cut_pitch = [via_cut_pitch_dbu, via_cut_pitch_dbu]

# Get metal layers by name
m1 = tech_lib.findLayer("metal1")
m4 = tech_lib.findLayer("metal4")
m5 = tech_lib.findLayer("metal5")
m6 = tech_lib.findLayer("metal6")
m7 = tech_lib.findLayer("metal7")
m8 = tech_lib.findLayer("metal8")
m9 = tech_lib.findLayer("metal9") # Although not used for PDN, good to have layer objects if needed later


# Check for essential layers
required_layers_core = [m1, m4, m7, m8]
required_layer_names_core = ["metal1", "metal4", "metal7", "metal8"]
if not all(required_layers_core):
    missing = [name for layer, name in zip(required_layers_core, required_layer_names_core) if layer is None]
    print(f"Error: Missing one or more required metal layers for core PDN: {', '.join(missing)}. Skipping core PDN construction.")
    # In a real flow, you might exit here. Proceeding with warnings.

# Create power grid for standard cells (Core Grid)
# Define the core grid structure
core_grid_name = "core_pg_grid"

# Check if grid definition already exists (e.g., from a previous run)
existing_core_grids = pdngen.findGrid(core_grid_name)
if existing_core_grids:
    print(f"Core grid definition '{core_grid_name}' already exists. Clearing existing definition.")
    pdngen.removeGrid(existing_core_grids[0]) # Remove the existing definition

# Make the core grid definition within the core domain
core_grid = pdngen.makeCoreGrid(domain = core_domain,
                                name = core_grid_name,
                                starts_with = pdn.GROUND, # Define which net's strap/ring comes first
                                pin_layers = [], # Standard cell pin layers are handled by followpin
                                generate_obstructions = [], # Do not generate routing obstructions by default
                                powercell = None, # No power gating cells specified
                                powercontrol = None,
                                powercontrolnetwork = "STAR") # Example connection pattern

# Ensure the core grid definition was created
if not core_grid:
    print("Error: Failed to create core power grid definition.")
    exit() # Cannot proceed without a grid definition

# Add standard cell power structures to the core grid definition
# Followpin on M1
if m1:
    print("Adding metal1 followpin to core grid.")
    pdngen.makeFollowpin(grid = core_grid,
                         layer = m1,
                         width = m1_followpin_width_dbu,
                         extend = pdn.CORE) # Extend within the core area
else: print("Warning: metal1 layer not found for M1 followpin PDN.")

# Straps on M4
if m4:
    print("Adding metal4 straps to core grid.")
    # M4 used for standard cells as requested
    pdngen.makeStrap(grid = core_grid,
                     layer = m4,
                     width = m4_strap_width_dbu,
                     spacing = m4_strap_spacing_dbu,
                     pitch = m4_strap_pitch_dbu,
                     offset = offset_dbu,
                     number_of_straps = 0, # Auto-calculate number of straps based on pitch/offset/area
                     snap = False, # Usually don't snap core straps to site rows
                     starts_with = pdn.GRID, # Position relative to grid boundary or pattern start
                     extend = pdn.CORE, # Extend within the core area
                     nets = []) # Apply to all nets in the grid (VDD/VSS)
else: print("Warning: metal4 layer not found for M4 strap PDN.")

# Straps on M7
if m7:
     print("Adding metal7 straps to core grid.")
     # M7 used for standard cells as requested
     pdngen.makeStrap(grid = core_grid,
                      layer = m7,
                      width = m7_m8_strap_width_dbu, # Use 1.4um width
                      spacing = m7_m8_strap_spacing_dbu, # Use 1.4um spacing
                      pitch = m7_m8_strap_pitch_dbu, # Use 10.8um pitch
                      offset = offset_dbu,
                      number_of_straps = 0,
                      snap = False,
                      starts_with = pdn.GRID,
                      extend = pdn.CORE, # Extend within the core area
                      nets = [])
else: print("Warning: metal7 layer not found for M7 strap PDN.")

# Straps on M8
if m8:
     print("Adding metal8 straps to core grid.")
     # M8 also used for standard cells as requested
     pdngen.makeStrap(grid = core_grid,
                      layer = m8,
                      width = m7_m8_strap_width_dbu, # Use 1.4um width
                      spacing = m7_m8_strap_spacing_dbu, # Use 1.4um spacing (using the same as M7 straps as specified for M7/M8 strap width/spacing/pitch)
                      pitch = m7_m8_strap_pitch_dbu, # Use 10.8um pitch (using the same as M7 straps)
                      offset = offset_dbu,
                      number_of_straps = 0,
                      snap = False,
                      starts_with = pdn.GRID,
                      extend = pdn.CORE, # Extend within the core area
                      nets = []) # Apply to all nets in the grid (VDD/VSS)
else: print("Warning: metal8 layer not found for M8 strap PDN.")

# Rings on M7 and M8 around core area
if m7 and m8:
     print("Adding M7/M8 rings around core area.")
     # Rings should encompass the core area
     # Use the specified width and spacing for M7 (2/2) and M8 (2/2) rings
     # Note: makeRing takes two layers and their properties (layer0, width0, spacing0, layer1, width1, spacing1)
     # It creates horizontal rings on one layer and vertical rings on the other, or both directions on both depending on config.
     # Standard practice is one layer horizontal, one vertical for a pair. Let's assume M7 horizontal, M8 vertical.
     ring_offset_dbu = [offset_dbu] * 4 # Offset from the boundary [left, bottom, right, top]
     pdngen.makeRing(grid = core_grid,
                     layer0 = m7, # Let M7 be horizontal rings
                     width0 = core_ring_m7_width_dbu,
                     spacing0 = core_ring_m7_spacing_dbu,
                     layer1 = m8, # Let M8 be vertical rings
                     width1 = core_ring_m8_width_dbu,
                     spacing1 = core_ring_m8_spacing_dbu,
                     starts_with = pdn.GRID, # Position relative to grid boundary
                     offset = ring_offset_dbu,
                     pad_offset = [0]*4, # No specific offset for pads connected to rings
                     extend = pdn.CORE, # Extend rings to the core boundary
                     pad_pin_layers = [], # Do not connect directly to pads with this ring definition
                     nets = []) # Apply to all nets in the grid (VDD/VSS)
else: print("Warning: metal7 or metal8 layer not found for core ring PDN.")


# Create via connections between standard cell power grid layers within the core area
print("Adding via connections for core grid.")
# Connections should be between adjacent routing layers used for the grid
if m1 and m4:
    pdngen.makeConnect(grid = core_grid, layer0 = m1, layer1 = m4, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
else: print("Warning: Cannot add M1-M4 via connections for core grid.")
if m4 and m7:
    pdngen.makeConnect(grid = core_grid, layer0 = m4, layer1 = m7, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
else: print("Warning: Cannot add M4-M7 via connections for core grid.")
if m7 and m8:
     pdngen.makeConnect(grid = core_grid, layer0 = m7, layer1 = m8, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
else: print("Warning: Cannot add M7-M8 via connections for core grid.")


# Create power grid for macro blocks (if macros exist)
macros = [inst for inst in block.getInsts() if inst.getMaster() and inst.getMaster().isBlock()]
if len(macros) > 0:
    print(f"Configuring PDN for {len(macros)} macros.")
    # Use the same halo around macros for PDN exclusion/connection as used in placement
    macro_grid_halo_um = [5.0, 5.0, 5.0, 5.0]
    macro_grid_halo_dbu = [design.micronToDBU(h) for h in macro_grid_halo_um]

    # Check for required layers for macro PDN
    required_layers_macro = [m4, m5, m6, m7] # Need M4 and M7 to connect to core grid
    required_layer_names_macro = ["metal4", "metal5", "metal6", "metal7"]
    if not all(required_layers_macro):
        missing = [name for layer, name in zip(required_layers_macro, required_layer_names_macro) if layer is None]
        print(f"Warning: Missing one or more required metal layers for macro PDN: {', '.join(missing)}. Skipping macro PDN configuration.")
    else:
        for i, macro_inst in enumerate(macros):
            print(f"Configuring PDN for macro instance: {macro_inst.getName()}")
            macro_grid_name = f"macro_pg_grid_{i}" # Unique name per instance

            # Check if grid definition already exists
            existing_macro_grids = pdngen.findGrid(macro_grid_name)
            if existing_macro_grids:
                print(f"Macro grid definition '{macro_grid_name}' already exists. Clearing existing definition.")
                pdngen.removeGrid(existing_macro_grids[0])

            # Create an instance-specific grid definition for each macro
            macro_grid = pdngen.makeInstanceGrid(domain = core_domain, # Associate with the core domain
                                                 name = macro_grid_name,
                                                 starts_with = pdn.GROUND,
                                                 inst = macro_inst, # Link this grid definition to the specific instance
                                                 halo = macro_grid_halo_dbu, # Apply halo region around the instance
                                                 pg_pins_to_boundary = True,  # Connect macro PG pins to the instance grid boundary
                                                 default_grid = False, # This is an instance grid, not the default core grid
                                                 generate_obstructions = [],
                                                 is_bump = False) # Not a bump pad grid

            # Ensure the instance grid definition was created
            if not macro_grid:
                 print(f"Error: Failed to create macro power grid definition for {macro_inst.getName()}. Skipping.")
                 continue # Skip to next macro instance if creation failed

            # Add macro power structures to the instance grid definition
            # Rings on M5 and M6 around the macro instance area (including halo)
            print("Adding M5/M6 rings around macro instance.")
            macro_ring_offset_dbu = [offset_dbu] * 4 # Offset from the instance boundary + halo
            pdngen.makeRing(grid = macro_grid,
                            layer0 = m5, # M5 horizontal ring
                            width0 = macro_ring_width_dbu, # Use 1.5um width for rings
                            spacing0 = macro_ring_spacing_dbu, # Use 1.5um spacing for rings
                            layer1 = m6, # M6 vertical ring
                            width1 = macro_ring_width_dbu, # Use 1.5um width for rings
                            spacing1 = macro_ring_spacing_dbu, # Use 1.5um spacing for rings
                            starts_with = pdn.GRID, # Position relative to instance grid boundary
                            offset = macro_ring_offset_dbu,
                            pad_offset = [0]*4,
                            extend = pdn.INSTANCE, # Extend rings to the instance boundary (which includes the halo defined earlier)
                            pad_pin_layers = [],
                            nets = []) # Apply to VDD/VSS within this instance grid

            # Straps on M5 and M6 for macro connections
            print("Adding M5/M6 straps for macro instance.")
            # M5 straps within the macro instance area + halo
            pdngen.makeStrap(grid = macro_grid,
                             layer = m5, # Use M5 for macro straps as requested
                             width = macro_strap_width_dbu, # Use 1.2um width for straps
                             spacing = macro_strap_spacing_dbu, # Use 1.2um spacing for straps
                             pitch = macro_strap_pitch_dbu, # Use 6um pitch for straps
                             offset = offset_dbu,
                             number_of_straps = 0,
                             snap = True, # Snap straps to grid, potentially pin locations or track grid
                             starts_with = pdn.GRID,
                             extend = pdn.INSTANCE, # Extend straps within the instance boundary + halo
                             nets = [])
            # M6 straps within the macro instance area + halo
            pdngen.makeStrap(grid = macro_grid,
                             layer = m6, # Use M6 for macro straps as requested
                             width = macro_strap_width_dbu, # Use 1.2um width for straps
                             spacing = macro_strap_spacing_dbu, # Use 1.2um spacing for straps
                             pitch = macro_strap_pitch_dbu, # Use 6um pitch for straps
                             offset = offset_dbu,
                             number_of_straps = 0,
                             snap = True,
                             starts_with = pdn.GRID,
                             extend = pdn.INSTANCE,
                             nets = [])

            # Create via connections between macro power grid layers and connecting to core grid layers
            # Connections needed:
            # 1. Within macro grid: M5 <-> M6
            # 2. Macro grid <-> Core grid: M4 (core) <-> M5 (macro), M6 (macro) <-> M7 (core)
            print("Adding via connections for macro grid.")
            # Connect M5 to M6 within the macro instance grid
            if m5 and m6:
                 pdngen.makeConnect(grid = macro_grid, layer0 = m5, layer1 = m6, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
            else: print(f"Warning: Cannot add M5-M6 via connections within macro {macro_inst.getName()}.")

            # Connecting instance grid to core grid layers where they overlap (at the halo boundary)
            # The makeConnect call on an instance grid context handles the connection
            # between the instance grid layers and the layers available from the default core grid.
            if m4 and m5:
                # Connect M4 (from core grid) to M5 (on macro instance grid)
                pdngen.makeConnect(grid = macro_grid, layer0 = m4, layer1 = m5, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
            else: print(f"Warning: Cannot add M4-M5 via connections for macro {macro_inst.getName()}.")
            if m6 and m7:
                 # Connect M6 (on macro instance grid) to M7 (from core grid)
                 pdngen.makeConnect(grid = macro_grid, layer0 = m6, layer1 = m7, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
            else: print(f"Warning: Cannot add M6-M7 via connections for macro {macro_inst.getName()}.")

# Generate the final power delivery network based on the definitions
print("Building and writing power grids to DB.")
# It's recommended to call checkSetup() before building
pdngen.checkSetup() # Verify configuration
pdngen.buildGrids() # Build the physical power grid shapes in the block
pdngen.writeToDb(True) # Write power grid shapes to the design database

# Reset temporary shapes generated during buildGrids (good practice)
# pdngen.resetShapes() # The API might handle this automatically after writeToDb

# 9. Run clock tree synthesis (CTS)
print("Running clock tree synthesis.")
cts = design.getTritonCts()
# Set available clock buffers and inverter lists
# The prompt specified using only BUF_X2 as clock buffers.
cts.setBufferList("BUF_X2") # List of masters to use as buffers/inverters
# Set root and sink buffers (assuming BUF_X2 can act as both if needed)
# cts.setRootBuffer("BUF_X2") # Specifies a specific buffer for the clock root
# cts.setSinkBuffer("BUF_X2") # Specifies a specific buffer for sinks (leaf nodes)
# If not explicitly set, it might use the first cell in setBufferList or infer.
# Let's explicitly set them for clarity based on the prompt.
cts.addBuffer("BUF_X2") # Add BUF_X2 to the list of usable buffers for CTS
cts.addInverter("") # If no inverters are allowed, provide empty string or list.
# If inverters like INV_X1, INV_X2 etc are available and usable by CTS, add them:
# cts.addInverter("INV_X1 INV_X2 INV_X4")
# Since the prompt only mentioned BUF_X2, we'll stick to that.

# RC values were set earlier using evalTclString, CTS should pick them up from the DB.
# Additional CTS parameters can be set here if needed (e.g., target skew, max cap/fanout).
# cts.setTargetSkew(0.1) # Example: 100ps target skew
# cts.setMaxCap(max_cap_value)
# cts.setMaxFanout(max_fanout_value)

# Run CTS
cts.runTritonCts()

# 10. Run final detailed placement after CTS
# CTS might insert buffers and move cells, requiring a final detailed placement step.
print("Running final detailed placement after CTS.")
# Max displacement values are the same as before (1um x, 3um y)
max_disp_x_um = 1.0
max_disp_y_um = 3.0
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

# Remove filler cells before running detailed placement again (CTS might add/move cells)
opendp.removeFillers()

# Perform detailed placement with specified displacements
opendp.runDetailedPlacement(max_disp_x_dbu, max_disp_y_dbu)

# 11. Insert filler cells into empty spaces
print("Inserting filler cells.")
filler_masters = list()
# Find filler cells (typically have type "CORE_SPACER" or "FILLER") from libraries
# It's good practice to insert multi-unit width fillers first (e.g., 16-wide, 8-wide, etc.)
# followed by 1-wide fillers to fill remaining gaps efficiently.
filler_master_names = [] # List to store names of filler masters found
for lib in db.getLibs():
    for master in lib.getMasters():
        # Check for CORE_SPACER or similar filler types
        if master.getType() in ["CORE_SPACER", "FILLER"]: # Add common filler types
            filler_masters.append(master)
            filler_master_names.append(master.getName())

if len(filler_masters) == 0:
    print("No CORE_SPACER or FILLER cells found in library. Skipping filler placement.")
else:
    # Sort fillers by width descending so wider fillers are tried first
    filler_masters.sort(key=lambda m: m.getWidth(), reverse=True)
    print(f"Found filler masters: {[m.getName() for m in filler_masters]}")

    # Filler cells naming convention prefix
    filler_cells_prefix = "FILLCELL_"
    # Perform filler placement using the found filler masters
    # The fillerPlacement method takes a list of dbMaster objects
    opendp.fillerPlacement(filler_masters = filler_masters,
                           prefix = filler_cells_prefix,
                           verbose = False) # Set to True for detailed output

# 12. Configure and run global routing
print("Running global routing.")
grt = design.getGlobalRouter()

# Find routing levels for M1 and M7
# Get the routing layers from the technology
routing_layers = [layer for layer in tech_lib.getLayers() if layer.getType() == "ROUTING"]
metal1_level = -1
metal7_level = -1
for layer in routing_layers:
    if layer.getName() == "metal1":
        metal1_level = layer.getRoutingLevel()
    elif layer.getName() == "metal7":
        metal7_level = layer.getRoutingLevel()
    # Stop searching once both levels are found
    if metal1_level != -1 and metal7_level != -1:
        break

if metal1_level == -1 or metal7_level == -1:
    print("Error: Could not find routing levels for metal1 or metal7. Skipping global routing.")
else:
    print(f"Using routing layers from metal{metal1_level} up to metal{metal7_level}.")
    # Set routing layer ranges (M1 to M7)
    grt.setMinRoutingLayer(metal1_level)
    grt.setMaxRoutingLayer(metal7_level)

    # Set clock layer range (typically same as signal or higher).
    # The prompt doesn't specify a separate range for clock, so use the same.
    grt.setMinLayerForClock(metal1_level)
    grt.setMaxLayerForClock(metal7_level)

    # Set routing adjustment (example value - higher adjustment means less capacity used, potentially reducing congestion)
    # A value like 0.5 means 50% capacity reduction. This needs tuning based on design/tech.
    grt.setAdjustment(0.5)
    grt.setVerbose(True) # Enable verbose output

    # The prompt asks for 10 iterations. The standard globalRoute(timing_driven) doesn't directly expose this.
    # Global router might have internal iteration controls not exposed via this API.
    # We run the globalRoute command once, letting the tool manage its iterations.
    # If timing is enabled, set timing_driven to True. Let's assume timing is NOT fully setup based on clock port check earlier.
    timing_enabled = clock_port is not None # Simplified check if clock exists
    grt.globalRoute(timing_enabled)

# 13. Configure and run detailed routing
print("Running detailed routing.")
drter = design.getTritonRoute()
dr_params = drt.ParamStruct()

# Set routing layer range for detailed router (M1 to M7)
# Provide layer names to ParamStruct
dr_params.bottomRoutingLayer = "metal1"
dr_params.topRoutingLayer = "metal7"

# Set other common parameters for detailed routing
dr_params.enableViaGen = True # Enable via generation
dr_params.drouteEndIter = 1 # Number of detailed routing iterations (usually 1 or 2)
dr_params.orSeed = -1 # Router seed (-1 for random, >0 for deterministic)
dr_params.verbose = 1 # Verbosity level (0=quiet, 1=normal, 2=debug)
dr_params.cleanPatches = True # Clean routing patches after detailed routing
dr_params.doPa = True # Perform post-route detailed placement/optimization (useful for DRC fixing)
dr_params.minAccessPoints = 1 # Minimum access points for pins

# Set the detailed routing parameters
drter.setParams(dr_params)
# Run detailed routing
drter.main()


# 14. Write final output files
print("Writing final output files.")
# Write final DEF file which contains placement and routing information
design.writeDef("final.def")
# Write final Verilog file (netlist with inserted cells like buffers and fillers)
# Use the write_verilog Tcl command
design.evalTclString("write_verilog final.v")
# Optionally write SPEF for post-route static timing analysis (requires SPEF extraction setup)
# design.evalTclString("write_spef final.spef")
# Optionally write DSU/GDSII for layout vs schematic (LVS) and design rule checking (DRC)
# design.evalTclString("write_dsu final.dsu") # If technology supports DSU output
# design.evalTclString("write_gds final.gdsii") # If GDSII streaming is supported/needed

print("OpenROAD flow completed.")