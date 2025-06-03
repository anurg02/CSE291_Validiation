import odb
import pdn
import openroad as ord
import drt
import sta # Renamed import to avoid shadowing the 'sta_tool' object later
import utl # Utility functions for messages

# Initialize the logger
# Log levels can be set here (utl.INFO, utl.WARNING, utl.ERROR, utl.DEBUG)
# Setting to INFO by default to see progress messages
utl.Log.setDebugFlag(utl.Log.ORD, False)
utl.Log.setDebugFlag(utl.Log.PDN, False)
utl.Log.setDebugFlag(utl.Log.CTS, False)
utl.Log.setDebugFlag(utl.Log.STA, False)
utl.Log.setDebugFlag(utl.Log.GPL, False)
utl.Log.setDebugFlag(utl.Log.MPL, False)
utl.Log.setDebugFlag(utl.Log.DPL, False)
utl.Log.setDebugFlag(utl.Log.GRT, False)
utl.Log.setDebugFlag(utl.Log.DRT, False)
utl.Log.setDebugFlag(utl.Log.IOPO, False)

# --- Design Loading and Library Reading ---
# IMPORTANT: Replace these placeholder file paths and top module name
# with your actual design files and top module name.
verilog_file = "your_design.v"       # <--- REPLACE with your Verilog netlist file
liberty_file = "your_lib.lib"       # <--- REPLACE with your Liberty file
lef_file = "your_tech.lef"          # <--- REPLACE with your Technology LEF file
top_module_name = "your_top_module_name" # <--- REPLACE with your design's top module name

utl.Log(utl.INFO, 0, "Loading design...")

# Create an empty design
design = ord.create_design()

# Read Verilog netlist
ord.read_verilog(verilog_file)

# Read LEF files (physical information, technology, layers, sites)
ord.read_lef(lef_file)

# Read liberty files (timing information)
ord.read_liberty(liberty_file)

# Link the design with the libraries
utl.Log(utl.INFO, 0, f"Linking design for top module '{top_module_name}'...")
ord.link_design(top_module_name)

# Get the database object
db = ord.get_db()
tech = db.getTech()
block = design.getBlock()

if block is None:
     utl.Log(utl.ERROR, 0, "Failed to create or link design block.")
     exit()

utl.Log(utl.INFO, 0, "Design loaded and linked.")


# --- Clock Setup ---
utl.Log(utl.INFO, 0, "Setting up clock.")
clock_period_ns = 20.0
clock_port_name = "clk" # Assuming the clock port is named 'clk' as requested
clock_name = "core_clock"

# Check if the clock port exists
clock_port = block.findBTerm(clock_port_name)
if clock_port is None:
    utl.Log(utl.ERROR, 0, f"Clock port '{clock_port_name}' not found in the design. Exiting.")
    exit()

# Create clock signal using Tcl (common practice and required by some tools)
ord.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")

# Propagate the clock signal for timing analysis (necessary for STA)
ord.evalTclString(f"set_propagated_clock [get_clocks {clock_name}]")
utl.Log(utl.INFO, 0, f"Clock '{clock_name}' with period {clock_period_ns} ns created on port '{clock_port_name}'.")


# --- Floorplanning ---
utl.Log(utl.INFO, 0, "Starting floorplanning.")

# Define floorplan parameters
target_util = 0.45
aspect_ratio = 1.0 # Assuming a square aspect ratio for simplicity, can be adjusted
core_to_die_margin_um = 5.0
core_to_die_margin_dbu = design.micronToDBU(core_to_die_margin_um)

# Find a suitable site from the technology library for floorplan rows
# IMPORTANT: Replace "site" with the actual site name from your LEF (e.g., "CORE" or a specific row site).
# This is crucial for determining row height and track spacing.
site_name = "site" # <--- **REPLACE "site" with actual site name from your LEF**
site = tech.findSite(site_name)
if site is None:
    utl.Log(utl.ERROR, 0, f"Could not find site '{site_name}'. Please update the script with the correct site name from your LEF. Exiting.")
    exit()

floorplan = design.getFloorplan()

# Initialize the floorplan using target utilization and core-to-die margin
# This overload creates the die area based on required core area (from utilization) + margin
# and sets the core area internally. The margin is applied equally to all sides here.
utl.Log(utl.INFO, 0, f"Initializing floorplan with target utilization {target_util}, aspect ratio {aspect_ratio}, and core-to-die margin {core_to_die_margin_um} um.")
floorplan.initFloorplan(site,
                        target_util,
                        aspect_ratio,
                        core_to_die_margin_dbu, # left margin
                        core_to_die_margin_dbu, # bottom margin
                        core_to_die_margin_dbu, # right margin
                        core_to_die_margin_dbu) # top margin

# Create placement tracks based on site definition
floorplan.makeTracks()
utl.Log(utl.INFO, 0, "Created placement tracks.")

# Save DEF file after floorplanning
design.writeDef("floorplan.def")
utl.Log(utl.INFO, 0, "Floorplan completed and saved to floorplan.def")


# --- I/O Pin Placement ---
utl.Log(utl.INFO, 0, "Starting I/O pin placement.")
io_placer = design.getIOPlacer()
io_params = io_placer.getParameters()

# Get metal layers for horizontal and vertical pin placement as requested (M8, M9)
m8 = tech.findLayer("metal8")
m9 = tech.findLayer("metal9")

io_layers_added = False
# It's crucial to check layer direction for pin placement
if m8 is not None and m8.getDirection() == odb.dbTechLayer.HORIZONTAL:
    io_placer.addHorLayer(m8)
    utl.Log(utl.INFO, 0, f"Added {m8.getName()} as horizontal layer for IO placement.")
    io_layers_added = True
elif m8 is not None:
     utl.Log(utl.WARNING, 0, f"Metal layer {m8.getName()} found but is not horizontal. Skipping for horizontal IOs.")
else:
    utl.Log(utl.WARNING, 0, "Could not find metal8 layer for IO placement.")


if m9 is not None and m9.getDirection() == odb.dbTechLayer.VERTICAL:
     io_placer.addVerLayer(m9)
     utl.Log(utl.INFO, 0, f"Added {m9.getName()} as vertical layer for IO placement.")
     io_layers_added = True
elif m9 is not None:
     utl.Log(utl.WARNING, 0, f"Metal layer {m9.getName()} found but is not vertical. Skipping for vertical IOs.")
else:
    utl.Log(utl.WARNING, 0, "Could not find metal9 layer for IO placement.")

if not io_layers_added:
     utl.Log(utl.ERROR, 0, "No valid horizontal or vertical layers found for IO placement (M8/M9). Cannot proceed. Exiting.")
     exit()

# Run the annealing-based IO placement
utl.Log(utl.INFO, 0, "Running I/O pin placement.")
io_placer.runAnnealing(True) # True enables random mode within annealing
utl.Log(utl.INFO, 0, "I/O pin placement completed.")

# Save DEF file after IO placement
design.writeDef("io_placed.def")
utl.Log(utl.INFO, 0, "I/O placement saved to io_placed.def")


# --- Macro Placement ---
utl.Log(utl.INFO, 0, "Starting macro placement.")
# Identify instances that are macros (have a block master)
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

macro_halo_um = 5.0
macro_halo_dbu = design.micronToDBU(macro_halo_um)

if len(macros) > 0:
    utl.Log(utl.INFO, 0, f"Found {len(macros)} macros. Running macro placement.")
    mpl = design.getMacroPlacer()
    block = design.getBlock()
    core = block.getCoreArea()

    # Configure and run macro placement
    # Note: The requested "each macro is at least 5 um to each other" constraint
    # is typically handled by placement engines using density control and halo
    # regions rather than a direct distance parameter between *all* macro pairs.
    # Setting a halo region helps keep standard cells and other macros away.
    utl.Log(utl.INFO, 0, f"Setting macro keepout/halo region to {macro_halo_um} um.")
    mpl.place(
        max_num_macro = len(macros), # Place all identified macros
        halo_width = macro_halo_um,  # Set halo width in microns
        halo_height = macro_halo_um, # Set halo height in microns
        # Constrain macros within the core area calculated during floorplan
        fence_lx = block.dbuToMicrons(core.xMin()),
        fence_ly = block.dbuToMicrons(core.yMin()),
        fence_ux = block.dbuToMicrons(core.xMax()),
        fence_uy = block.dbuToMicrons(core.yMax()),
        target_util = target_util, # Pass target utilization to guide standard cell area distribution
        # Add other parameters as needed for your flow (e.g., weights, boundaries)
    )
    utl.Log(utl.INFO, 0, "Macro placement completed.")
else:
    utl.Log(utl.INFO, 0, "No macros found in the design. Skipping macro placement.")


# --- Standard Cell Global Placement ---
utl.Log(utl.INFO, 0, "Starting standard cell global placement.")
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Disable timing-driven mode for simplicity
gpl.setRoutabilityDrivenMode(True) # Enable routability-driven mode
gpl.setUniformTargetDensityMode(True) # Use uniform target density

# Perform initial placement (quadratic)
utl.Log(utl.INFO, 0, "Running initial global placement.")
gpl.doInitialPlace()

# Perform Nesterov placement (nonlinear optimization)
utl.Log(utl.INFO, 0, "Running Nesterov global placement.")
gpl.doNesterovPlace()

gpl.reset() # Reset placer state
utl.Log(utl.INFO, 0, "Global placement completed.")


# --- Initial Detailed Placement ---
utl.Log(utl.INFO, 0, "Starting initial detailed placement.")
dp = design.getOpendp()

# Get site dimensions to calculate displacement limits
rows = design.getBlock().getRows()
if not rows:
     utl.Log(utl.ERROR, 0, "No placement rows found. Detailed placement displacement limits may not be set optimally.")
     # Proceeding but this is a potential issue depending on DP implementation and desired behavior.
     # A robust script might exit or try to infer site properties differently.

# Define maximum displacement in microns
max_disp_x_um = 1.0
max_disp_y_um = 3.0

# Convert maximum displacement to DBUs. OpenDP detailedPlacement API expects DBU values.
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

# Remove existing filler cells before detailed placement (good practice)
dp.removeFillers()

# Perform detailed placement with specified max displacement
# detailedPlacement(max_disp_x, max_disp_y, cell_name, force_power_pins)
# The cell_name param is for specific cell placement, "" for all standard cells
# force_power_pins aligns cell power pins to tracks.
utl.Log(utl.INFO, 0, f"Running initial detailed placement with max displacement {max_disp_x_um} um (X), {max_disp_y_um} um (Y).")
# The API detailedPlacement takes displacement in DBU.
dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", True) # Force power pins alignment
utl.Log(utl.INFO, 0, "Initial detailed placement completed.")

# Save DEF file after placement (Global + Detailed)
design.writeDef("placement.def")
utl.Log(utl.INFO, 0, "Placement (Global + Detailed) saved to placement.def")


# --- Power Delivery Network (PDN) Construction ---
utl.Log(utl.INFO, 0, "Starting PDN construction.")

# Get the PDN generator object
pdngen = design.getPdnGen()

# Mark power and ground nets as special nets if not already done by global connect
# Find existing power and ground nets or create if needed
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")

if VDD_net is None:
    VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
    utl.Log(utl.INFO, 0, "Created VDD net.")
if VSS_net is None:
    VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
    utl.Log(utl.INFO, 0, "Created VSS net.")

# Set signal type and special property
VDD_net.setSigType("POWER")
VSS_net.setSigType("GROUND")
VDD_net.setSpecial()
VSS_net.setSpecial()
utl.Log(utl.INFO, 0, "Ensured VDD/VSS nets exist and are marked as special POWER/GROUND.")

# Connect power pins of instances to global power/ground nets using Global Connect
# This needs to happen before PDN generation relies on it.
utl.Log(utl.INFO, 0, "Connecting power and ground pins via Global Connect.")
# Remove existing global connects to avoid duplicates if script is run multiple times
design.getBlock().removeGlobalConnects()
# Add connections - use pin patterns common in libraries (adjust if needed based on your library)
# Using broad patterns like ".*" for instance names and "^VDD$"/"^VSS$" for pin names is common.
design.getBlock().addGlobalConnect(region = None, instPattern = "*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = "*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
# Consider adding other common power/ground pin names if your library uses them
# design.getBlock().addGlobalConnect(region = None, instPattern = "*", pinPattern = "^VDDPE$", net = VDD_net, do_connect = True)
# design.getBlock().addGlobalConnect(region = None, instPattern = "*", pinPattern = "^VSSCE$", net = VSS_net, do_connect = True)

# Apply the global connections
design.getBlock().globalConnect()
utl.Log(utl.INFO, 0, "Global Connect completed.")

# Set the core voltage domain with the primary power and ground nets
pdngen.setCoreDomain(power = VDD_net, ground = VSS_net) # No switched power or secondary nets requested
utl.Log(utl.INFO, 0, "Core power domain set.")

# Set via cut pitch between parallel grids to 0 μm (0 DBU) as requested
# This applies to connections *between* different layers of the same grid,
# and when connecting instance grids to core grids.
pdn_cut_pitch_x_um = 0.0
pdn_cut_pitch_y_um = 0.0
pdn_cut_pitch_x = design.micronToDBU(pdn_cut_pitch_x_um)
pdn_cut_pitch_y = design.micronToDBU(pdn_cut_pitch_y_um)

# Get metal layers for PDN implementation
m1 = tech.findLayer("metal1")
m4 = tech.findLayer("metal4")
m5 = tech.findLayer("metal5")
m6 = tech.findLayer("metal6")
m7 = tech.findLayer("metal7")
m8 = tech.findLayer("metal8")

# Check if necessary layers exist
required_layers = {"metal1": m1, "metal4": m4, "metal7": m7, "metal8": m8}
if len(macros) > 0:
    required_layers["metal5"] = m5
    required_layers["metal6"] = m6

all_layers_found = True
for layer_name, layer_obj in required_layers.items():
    if layer_obj is None:
        utl.Log(utl.ERROR, 0, f"Required layer '{layer_name}' not found for PDN construction. Please check LEF. Exiting.")
        all_layers_found = False

if not all_layers_found:
    exit() # Cannot proceed without required layers


# Create power grid for standard cells and core
# Using the 'Core' domain created earlier
domain = pdngen.findDomain("Core")
if domain is None:
    utl.Log(utl.ERROR, 0, "Core domain not found during PDN construction setup. Exiting.")
    exit()

# Create the main core grid structure (standard cells and higher layers)
utl.Log(utl.INFO, 0, "Creating core grid.")
# starts_with=pdn.GROUND determines the VSS/VDD pattern starting from the boundary/origin.
# Using pdn.GRID means the pattern starts based on the grid's origin.
pdngen.makeCoreGrid(domain = domain,
                    name = "core_grid",
                    starts_with = pdn.GRID) # Using pdn.GRID for typical alternating pattern

core_grids = pdngen.findGrid("core_grid")
if not core_grids: # findGrid returns a list
    utl.Log(utl.ERROR, 0, "Core grid not created. Exiting.")
    exit()
core_grid = core_grids[0] # Assume there's only one core grid created by makeCoreGrid

# Configure PDN for standard cells in the core grid
# makeCoreGrid creates the grid structure, subsequent calls define straps/rings/connections on it.

# Create horizontal followpin straps on metal1 for standard cells
# M1 grid width 0.07 um requested. Note: Followpin uses width parameter.
m1_width_um = 0.07
utl.Log(utl.INFO, 0, f"Adding M1 followpins (width {m1_width_um} um) to core grid.")
pdngen.makeFollowpin(grid = core_grid,
                     layer = m1,
                     width = design.micronToDBU(m1_width_um),
                     extend = pdn.CORE) # Extend straps within the core area

# Create straps on metal4 in the core grid (for standard cells and connecting to macros)
# M4 grid width 1.2 um, spacing 1.2 um, pitch 6 um, offset 0 um requested.
m4_width_um = 1.2
m4_spacing_um = 1.2
m4_pitch_um = 6.0
m4_offset_um = 0.0
utl.Log(utl.INFO, 0, f"Adding M4 straps (width {m4_width_um}, spacing {m4_spacing_um}, pitch {m4_pitch_um}, offset {m4_offset_um} um) to core grid.")
pdngen.makeStrap(grid = core_grid,
                 layer = m4,
                 width = design.micronToDBU(m4_width_um),
                 spacing = design.micronToDBU(m4_spacing_um),
                 pitch = design.micronToDBU(m4_pitch_um),
                 offset = design.micronToDBU(m4_offset_um),
                 starts_with = pdn.GRID, # Start pattern based on grid origin
                 extend = pdn.CORE) # Extend within the core area

# Create straps on metal7 for core grid
# M7 grid width 1.4 um, spacing 1.4 um, pitch 10.8 um, offset 0 um requested.
m7_strap_width_um = 1.4
m7_strap_spacing_um = 1.4
m7_strap_pitch_um = 10.8
m7_strap_offset_um = 0.0
utl.Log(utl.INFO, 0, f"Adding M7 straps (width {m7_strap_width_um}, spacing {m7_strap_spacing_um}, pitch {m7_strap_pitch_um}, offset {m7_strap_offset_um} um) to core grid.")
pdngen.makeStrap(grid = core_grid,
                 layer = m7,
                 width = design.micronToDBU(m7_strap_width_um),
                 spacing = design.micronToDBU(m7_strap_spacing_um),
                 pitch = design.micronToDBU(m7_strap_pitch_um),
                 offset = design.micronToDBU(m7_strap_offset_um),
                 starts_with = pdn.GRID,
                 extend = pdn.CORE)

# Create straps on metal8 for core grid (using M7 strap parameters as M8 strap params weren't explicitly given)
# Assuming M8 strap width 1.4 um, spacing 1.4 um, pitch 10.8 um, offset 0 um.
m8_strap_width_um = 1.4 # Based on M7 strap
m8_strap_spacing_um = 1.4 # Based on M7 strap
m8_strap_pitch_um = 10.8 # Based on M7 strap
m8_strap_offset_um = 0.0
utl.Log(utl.INFO, 0, f"Adding M8 straps (width {m8_strap_width_um}, spacing {m8_strap_spacing_um}, pitch {m8_strap_pitch_um}, offset {m8_strap_offset_um} um) to core grid.")
pdngen.makeStrap(grid = core_grid,
                 layer = m8,
                 width = design.micronToDBU(m8_strap_width_um),
                 spacing = design.micronToDBU(m8_strap_spacing_um),
                 pitch = design.micronToDBU(m8_strap_pitch_um),
                 offset = design.micronToDBU(m8_strap_offset_um),
                 starts_with = pdn.GRID,
                 extend = pdn.CORE)

# Create power rings on metal7 and metal8 around the core boundary
# M7 rings width 2 um, spacing 2 um. M8 rings width 2 um, spacing 2 um. Offset 0 um.
# makeRing offset parameter is [left, bottom, right, top]
core_ring_width_um = 2.0
core_ring_spacing_um = 2.0
core_ring_offset_um = 0.0
core_ring_offset_dbu = [design.micronToDBU(core_ring_offset_um) for _ in range(4)] # Apply 0 offset to all sides

# Check layer directions for rings. M7 usually horizontal, M8 usually vertical.
# If directions are different in your LEF, swap layer0 and layer1 or update prompt.
if m7.getDirection() != odb.dbTechLayer.HORIZONTAL or m8.getDirection() != odb.dbTechLayer.VERTICAL:
    utl.Log(utl.WARNING, 0, f"M7 ({m7.getName()}) is {m7.getDirection()} and M8 ({m8.getName()}) is {m8.getDirection()}. Ring layers assumed to be M7 horizontal, M8 vertical based on typical usage. Adjust makeRing call if directions are swapped.")


utl.Log(utl.INFO, 0, f"Adding M7/M8 rings (width {core_ring_width_um}, spacing {core_ring_spacing_um}, offset {core_ring_offset_um} um) around the core boundary.")
pdngen.makeRing(grid = core_grid,
                layer0 = m7, # Layer for horizontal rings (assuming M7 is horizontal)
                width0 = design.micronToDBU(core_ring_width_um),
                spacing0 = design.micronToDBU(core_ring_spacing_um),
                layer1 = m8, # Layer for vertical rings (assuming M8 is vertical)
                width1 = design.micronToDBU(core_ring_width_um),
                spacing1 = design.micronToDBU(core_ring_spacing_um),
                starts_with = pdn.GRID, # Start pattern related to grid (VSS/VDD alternation)
                offset = core_ring_offset_dbu, # Offset relative to core boundary
                pad_offset = [design.micronToDBU(0) for _ in range(4)], # Pad offset 0 um requested (makeRing uses this)
                extend = False, # Do not extend the ring beyond offset
                allow_out_of_die = True) # Allow rings to slightly cross die boundary if needed


# Create via connections between standard cell grid layers (M1->M4->M7->M8)
# Via pitch 0 um (0 DBU) between parallel grids as requested.
utl.Log(utl.INFO, 0, f"Adding via connections in core grid (cut pitch {pdn_cut_pitch_x_um} um).")
pdngen.makeConnect(grid = core_grid, layer0 = m1, layer1 = m4, cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y, offset = design.micronToDBU(0)) # offset 0 um requested
pdngen.makeConnect(grid = core_grid, layer0 = m4, layer1 = m7, cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y, offset = design.micronToDBU(0)) # offset 0 um requested
pdngen.makeConnect(grid = core_grid, layer0 = m7, layer1 = m8, cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y, offset = design.micronToDBU(0)) # offset 0 um requested


# Configure PDN for macro blocks if they exist
# If the design has macros, build power grids for macros on M5 and M6.
# M5 and M6 grid width 1.2 um, spacing 1.2 um, pitch 6 um, offset 0 um requested.
if len(macros) > 0:
    utl.Log(utl.INFO, 0, "Configuring PDN for macros.")
    # Use macro halo for PDN instance grid extension
    # The 'halo' parameter in makeInstanceGrid is [left, bottom, right, top] offset *from macro boundary*
    # We use the same macro_halo_um as set during macro placement.
    pdn_macro_halo_dbu = [macro_halo_dbu, macro_halo_dbu, macro_halo_dbu, macro_halo_dbu]

    m5_width_um = 1.2
    m5_spacing_um = 1.2
    m5_pitch_um = 6.0
    m5_offset_um = 0.0 # Offset 0 um requested

    m6_width_um = 1.2
    m6_spacing_um = 1.2
    m6_pitch_um = 6.0
    m6_offset_um = 0.0 # Offset 0 um requested

    for i, macro_inst in enumerate(macros):
        # Create a separate instance grid for each macro instance
        # Note: This creates a grid centered on the macro instance and extending by the halo.
        utl.Log(utl.INFO, 0, f"Creating instance grid 'macro_grid_{i}' for macro '{macro_inst.getName()}'.")
        pdngen.makeInstanceGrid(domain = domain, # Use the same core domain
                                name = f"macro_grid_{i}",
                                starts_with = pdn.GRID, # Start pattern based on grid origin
                                inst = macro_inst,
                                halo = pdn_macro_halo_dbu, # Set halo around the macro
                                pg_pins_to_boundary = True) # Connect PG pins to the macro boundary

        macro_grids_list = pdngen.findGrid(f"macro_grid_{i}")
        if not macro_grids_list: # findGrid returns a list
             utl.Log(utl.ERROR, 0, f"Macro instance grid macro_grid_{i} not created. Skipping PDN for this macro.")
             continue
        macro_grid = macro_grids_list[0] # Assume one grid per instance

        # Create power straps on metal5 for macro connections
        utl.Log(utl.INFO, 0, f"Adding M5 straps (width {m5_width_um}, spacing {m5_spacing_um}, pitch {m5_pitch_um}, offset {m5_offset_um} um) to macro grid {i}.")
        pdngen.makeStrap(grid = macro_grid,
                         layer = m5,
                         width = design.micronToDBU(m5_width_um),
                         spacing = design.micronToDBU(m5_spacing_um),
                         pitch = design.micronToDBU(m5_pitch_um),
                         offset = design.micronToDBU(m5_offset_um),
                         starts_with = pdn.GRID,
                         extend = pdn.CORE) # Extend within macro core area (using CORE context of the instance grid)

        # Create power straps on metal6 for macro connections
        utl.Log(utl.INFO, 0, f"Adding M6 straps (width {m6_width_um}, spacing {m6_spacing_um}, pitch {m6_pitch_um}, offset {m6_offset_um} um) to macro grid {i}.")
        pdngen.makeStrap(grid = macro_grid,
                         layer = m6,
                         width = design.micronToDBU(m6_width_um),
                         spacing = design.micronToDBU(m6_spacing_um),
                         pitch = design.micronToDBU(m6_pitch_um),
                         offset = design.micronToDBU(m6_offset_um),
                         starts_with = pdn.GRID,
                         extend = pdn.CORE) # Extend within macro core area


        # Create via connections between macro grid layers and connect to core grid M4/M7
        # Connections requested: M4->M5, M5->M6, M6->M7. Via cut pitch 0 um.
        # This assumes M4 and M7 are part of the macro grid definition or accessible
        # layers for connectivity. makeInstanceGrid typically includes core layers.
        utl.Log(utl.INFO, 0, f"Adding M4-M5 via connections in macro grid {i} (cut pitch {pdn_cut_pitch_x_um} um).")
        pdngen.makeConnect(grid = macro_grid, layer0 = m4, layer1 = m5, cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y, offset = design.micronToDBU(0)) # offset 0 um requested
        utl.Log(utl.INFO, 0, f"Adding M5-M6 via connections in macro grid {i} (cut pitch {pdn_cut_pitch_x_um} um).")
        pdngen.makeConnect(grid = macro_grid, layer0 = m5, layer1 = m6, cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y, offset = design.micronToDBU(0)) # offset 0 um requested
        utl.Log(utl.INFO, 0, f"Adding M6-M7 via connections in macro grid {i} (cut pitch {pdn_cut_pitch_x_um} um).")
        pdngen.makeConnect(grid = macro_grid, layer0 = m6, layer1 = m7, cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y, offset = design.micronToDBU(0)) # offset 0 um requested


# Verify and build the power delivery network
utl.Log(utl.INFO, 0, "Building PDN.")
pdngen.checkSetup() # Verify the PDN configuration
# The following command generates the physical shapes in memory.
# The 'false' argument prevents regenerating shapes if they already exist.
pdngen.buildGrids(False)
# The following command commits the generated shapes to the OpenDB database.
pdngen.writeToDb(True) # True means commit changes.
# Reset temporary shapes used during generation to free memory
pdngen.resetShapes()
utl.Log(utl.INFO, 0, "PDN built and written to DB.")

# Save DEF file after PDN creation
design.writeDef("pdn.def")
utl.Log(utl.INFO, 0, "PDN saved to pdn.def")


# --- IR Drop Analysis and Power Reporting ---
utl.Log(utl.INFO, 0, "Starting power and IR drop analysis.")
# Get the STA object
sta_tool = design.getSta() # Renamed object to 'sta_tool'

# Set the unit resistance and capacitance values for wires as requested
# This needs library data loaded, which open_design, read_liberty, read_lef handle.
# Wire model is often already set by technology LEF/LIB, but can be overridden.
wire_res = 0.03574 # unit resistance
wire_cap = 0.07516 # unit capacitance
utl.Log(utl.INFO, 0, f"Setting wire RC values: R={wire_res}, C={wire_cap}.")
sta_tool.evalTclString(f"set_wire_rc -clock -resistance {wire_res} -capacitance {wire_cap}")
sta_tool.evalTclString(f"set_wire_rc -signal -resistance {wire_res} -capacitance {wire_cap}")

# Perform power analysis including IR drop.
# NOTE: The requested analysis *specifically* on "M1 nodes" of the power grids
# cannot be performed using the current `sta_tool.analyzePower(ir_drop=True)`
# Python API. This function performs general vectorless IR analysis across
# the entire PDN based on the voltage configuration and grid shapes.
# More granular or layer-specific IR analysis often requires Tcl commands
# (`report_power -ir_drop_per_instance` or similar) or external tools.
utl.Log(utl.INFO, 0, "Running power and IR drop analysis (whole PDN).")
# NOTE: For accurate switching power, activity data (like a VCD or SAIF file)
# needs to be loaded *before* calling analyzePower. Without it, switching power
# will be 0 or based on default estimates, and IR drop analysis will be vectorless.
# Loading activity file example (replace with actual path):
# sta_tool.evalTclString("read_activity_file -format VCD path/to/your/activity.vcd")
sta_tool.analyzePower(ir_drop=True) # ir_drop=True enables vectorless IR analysis

# Report power metrics (switching, leakage, internal, total) as requested.
utl.Log(utl.INFO, 0, "Reporting power:")
sta_tool.reportPower()
utl.Log(utl.INFO, 0, "Power and IR drop analysis completed.")


# --- Clock Tree Synthesis (CTS) ---
utl.Log(utl.INFO, 0, "Starting CTS.")
cts = design.getTritonCts()
cts_parms = cts.getParms()

# Set clock nets to be synthesized
cts.setClockNets(clock_name) # Use the clock name created earlier

# Configure clock buffers using the specified cell name ("BUF_X2")
buffer_cell_name = "BUF_X2" # Assuming "BUF_X2" is the liberty cell name
utl.Log(utl.INFO, 0, f"Using '{buffer_cell_name}' as clock buffer.")
# Check if the buffer cell exists in libraries
buffer_master = db.findMaster(buffer_cell_name)
if buffer_master is None:
     utl.Log(utl.ERROR, 0, f"Buffer cell '{buffer_cell_name}' not found in libraries. Please check LIB files. Exiting.")
     exit()

# Set the list of buffers CTS can use
cts.setBufferList(buffer_cell_name)
# Optionally set the root buffer if different, but prompt implies BUF_X2 for all.
# cts.setRootBuffer(buffer_cell_name) # Set root buffer

# Other CTS parameters can be set via cts_parms object or Tcl commands if API is missing
# Example: cts_parms.setTargetSkew(design.micronToDBU(0.05)) # Example target skew in DBU

# Run the Clock Tree Synthesis process
utl.Log(utl.INFO, 0, "Running TritonCTS.")
cts.runTritonCts()
utl.Log(utl.INFO, 0, "CTS completed.")


# --- Post-CTS Detailed Placement ---
# Required to optimize placement after CTS buffer insertion
utl.Log(utl.INFO, 0, "Starting post-CTS detailed placement.")
dp = design.getOpendp() # Get OpenDP object again

# Use the same max displacement settings as before
# max_disp_x_dbu, max_disp_y_dbu calculated earlier

# Remove existing filler cells before detailed placement (good practice)
dp.removeFillers()

# Perform detailed placement
utl.Log(utl.INFO, 0, f"Running post-CTS detailed placement with max displacement {max_disp_x_um} um (X), {max_disp_y_um} um (Y).")
# API expects DBU for displacement.
dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", True) # Force power pins alignment
utl.Log(utl.INFO, 0, "Post-CTS detailed placement completed.")


# --- Filler Cell Insertion ---
utl.Log(utl.INFO, 0, "Inserting filler cells.")
# Get a list of filler cell masters from the library
db = ord.get_db()
filler_masters = list()
# Common pattern for filler cell names, adjust based on your library
# Look for CORE_SPACER masters or specific filler names
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
             # Add all CORE_SPACER masters found.
             # A more advanced script might filter/sort them or specify a list to prioritize larger fillers.
             filler_masters.append(master)

if not filler_masters:
    utl.Log(utl.WARNING, 0, "No CORE_SPACER cells found in libraries for filler placement. Skipping.")
else:
    # Perform filler cell placement
    utl.Log(utl.INFO, 0, f"Running filler cell insertion using {len(filler_masters)} filler master type(s).")
    dp.fillerPlacement(filler_masters = filler_masters,
                       verbose = False)
    utl.Log(utl.INFO, 0, "Filler cell insertion completed.")


# Save DEF file after CTS, post-CTS placement, and filler insertion
design.writeDef("cts.def")
utl.Log(utl.INFO, 0, "CTS and post-placement saved to cts.def")


# --- Global Routing ---
utl.Log(utl.INFO, 0, "Starting global routing.")
grt = design.getGlobalRouter()

# Get the routing layers for the specified metal range (M1 to M7)
if m1 is None or m7 is None:
    utl.Log(utl.ERROR, 0, "M1 or M7 layer not found. Cannot configure global routing layers. Exiting.")
    exit()

signal_low_layer_level = m1.getRoutingLevel()
signal_high_layer_level = m7.getRoutingLevel()

# Set the minimum and maximum routing layers for signal nets
grt.setMinRoutingLayer(signal_low_layer_level)
grt.setMaxRoutingLayer(signal_high_layer_level)
utl.Log(utl.INFO, 0, f"Set signal routing layers from {m1.getName()} (level {signal_low_layer_level}) to {m7.getName()} (level {signal_high_layer_level}).")

# Use the same layers for clock routing (optional, but consistent with routing M1-M7)
grt.setMinLayerForClock(signal_low_layer_level)
grt.setMaxLayerForClock(signal_high_layer_level)
utl.Log(utl.INFO, 0, f"Set clock routing layers from {m1.getName()} to {m7.getName()}.")

# Set congestion adjustment
grt.setAdjustment(0.5) # Example adjustment factor, tune as needed

# The prompt requested setting global router iterations to 10.
# NOTE: The current Python API `grt.globalRoute(True)` does not expose a parameter
# to directly control the number of iterations for the default GR algorithm.
# This specific requirement from the prompt cannot be precisely met with this API call.
# The tool will run its internal iterative process towards convergence.
utl.Log(utl.INFO, 0, "Running global routing.")
grt.globalRoute(True) # True to generate guides for detailed routing
utl.Log(utl.INFO, 0, "Global routing completed.")

# Save DEF file after global routing
design.writeDef("global_route.def")
utl.Log(utl.INFO, 0, "Global routing saved to global_route.def")


# --- Detailed Routing ---
utl.Log(utl.INFO, 0, "Starting detailed routing.")
drter = design.getTritonRoute()

# Get default detailed router parameters
droute_params = drt.ParamStruct()

# Configure detailed routing parameters based on common practice and prompt constraints
# Set the bottom and top routing layers using layer objects
if m1 is None or m7 is None:
    utl.Log(utl.ERROR, 0, "M1 or M7 layer not found. Cannot configure detailed routing layers. Exiting.")
    exit()

# Use layer names for API parameter
droute_params.bottomRoutingLayer = m1.getName()
droute_params.topRoutingLayer = m7.getName()
utl.Log(utl.INFO, 0, f"Set detailed routing layers from {m1.getName()} to {m7.getName()}.")

# Enable via generation
droute_params.enableViaGen = True
# Number of detailed routing iterations (1 is common for basic run, more for convergence)
droute_params.drouteEndIter = 1 # Default or common value, can be increased for convergence

# Other common parameters (can be tuned)
droute_params.verbose = 1 # Set verbosity level (0=quiet, 1=normal, 2=detailed)
droute_params.cleanPatches = True # Clean up routing patches after completion
droute_params.doPa = True # Enable pin access (necessary for correct routing)
droute_params.minAccessPoints = 1 # Minimum access points for pins

# Set the configured parameters
drter.setParams(droute_params)

# Run detailed routing
utl.Log(utl.INFO, 0, "Running TritonRoute.")
drter.main()
utl.Log(utl.INFO, 0, "Detailed routing completed.")

# Save final DEF file after detailed routing
design.writeDef("final.def")
utl.Log(utl.INFO, 0, "Final routed design saved to final.def")

# Save final ODB database file
design.writeDb("final.odb")
utl.Log(utl.INFO, 0, "Final database saved to final.odb")

# --- Finalization ---
utl.Log(utl.INFO, 0, "Script finished.")

# Optional: Save final Verilog (netlist is same, but useful for consistency)
# Note: write_verilog often needs Tcl interface.
# ord.evalTclString("write_verilog final.v")
# utl.Log(utl.INFO, 0, "Final Verilog netlist saved to final.v")

# Optional: Exit OpenROAD cleanly
# ord.finishOpenRoad()