# This script performs a basic OpenROAD placement flow in Python,
# including clock definition, floorplanning, I/O placement, macro placement,
# global placement, detailed placement, and incorporates a setting for Global Router
# iterations based on the provided prompt and verification feedback.

# Assume the design (netlist) and technology (LEF) are already loaded.
# Example commands (uncomment and modify as needed):
# design.readLef("tech.lef")
# design.readVerilog("design.v")
# design.linkDesign("top_module") # Link netlist to library cells

import odb
import ifp # Initial Floorplan
import mpl # Macro Placer
import replace # Global Placement
import opendp # Detailed Placement
import ioplacer # IO Placer
import grt # Global Router Tool (added for correction)
# Unused imports from original drafts: cts

# Access the OpenROAD global object 'design'
# This object provides access to various OpenROAD tools and the design database
# Example:
# design = OpenROAD.getDesign() # Assumes OpenROAD object is available as 'OpenROAD'
# Note: In a typical OpenROAD shell or flow script, 'design' is usually
# automatically available as the main OpenROAD object or equivalent handle
# to the current design database and tool manager. This script assumes 'design'
# is already defined and accessible.

# --- Setup: Find Site and Tech Data ---
# Need site information for floorplanning and detailed placement calculations.
print("--- Initial Setup ---")
tech = design.getTech()
if not tech:
    print("Error: Technology data not loaded. Ensure LEF is read.")
    exit()
db = tech.getDB()
if not db:
     print("Error: Database not accessible from Tech.")
     exit()

site = None
site_width_dbu = -1
site_height_dbu = -1

# Iterate through libraries to find a suitable site for standard cells
# Standard cell sites typically have class 'CORE' or 'SITE'
for lib in db.getLibs():
    for potential_site in lib.getSites():
         site_class = potential_site.getClass()
         if site_class == 'CORE' or site_class == 'SITE':
             site = potential_site
             site_width_dbu = site.getWidth()
             site_height_dbu = site.getHeight()
             print(f"Found suitable site: {site.getName()} with class {site_class}. Dimensions: {design.dbuToMicrons(site_width_dbu):.3f}x{design.dbuToMicrons(site_height_dbu):.3f} um")
             break
    if site:
        break # Site found, exit outer loop

if not site:
    print("Error: No suitable CORE or SITE found in the library for floorplanning/placement.")
    exit()

block = design.getBlock()
if not block:
    print("Error: Design block not loaded. Ensure netlist and libraries are read.")
    exit()

print("-" * 20)

# --- 1. Clock Definition ---
# Create a clock signal on the clk_i port with a period of 20 ns and name it core_clock.
print("\n--- Clock Definition ---")

clk_port = block.findBTerm("clk_i")
if not clk_port:
    print("Error: Clock port 'clk_i' not found in the design.")
    # Exit or handle the error appropriately
    # In a full flow, you might check if clk_i is truly required or if another clock exists
    exit()

# Create the clock using the TCL command interface via evalTclString
# This is a robust way to ensure complex TCL commands are executed correctly.
# Using get_ports from TCL ensures the object is retrieved within the TCL context.
design.evalTclString("create_clock -period 20.0 [get_ports clk_i] -name core_clock")

# Propagate the clock signal (important for timing analysis during placement stages)
# This command makes the clock signal "visible" inside the design, not just on the port.
design.evalTclString("set_propagated_clock [get_clocks {core_clock}]")
print("Clock 'core_clock' defined on port 'clk_i' with period 20 ns.")
print("-" * 20)

# --- 2. Floorplanning ---
print("\n--- Floorplanning ---")
# Get the Floorplan tool instance
floorplan = design.getFloorplan()
if not floorplan:
    print("Error: Floorplan tool not initialized.")
    exit()

# Define core-to-die spacing in microns and target utilization as requested
core_margin_um = 10.0
target_utilization = 0.35

# Convert core margin to Database Units (DBU) for the floorplan tool
core_margin_dbu = design.micronToDBU(core_margin_um)

# Initialize floorplan. This function calculates the die and core area
# based on total instance area, core margin, target utilization, and site dimensions.
# It assumes a rectangular floorplan based on the total area of standard cells.
print(f"Initializing floorplan with core margin {core_margin_um} um and target utilization {target_utilization}...")
# Use the pre-found site object
floorplan.initFloorplan(core_margin_dbu, site, target_utilization)
print("Floorplan initialized.")

# Make routing tracks based on the floorplan and technology
# This step defines the grid used by placers and routers.
print("Creating routing tracks...")
floorplan.makeTracks()
print("Routing tracks created.")

# Get the final calculated core area after floorplanning for later use (e.g., macro fence)
block = design.getBlock() # Re-get block in case floorplan modified it
core_area = block.getCoreArea()
die_area = block.getDieArea()
print(f"Floorplan Core Area: X={design.dbuToMicrons(core_area.xMin()):.2f} Y={design.dbuToMicrons(core_area.yMin()):.2f} W={design.dbuToMicrons(core_area.getWidth()):.2f} H={design.dbuToMicrons(core_area.getHeight()):.2f} um")
print(f"Floorplan Die Area: X={design.dbuToMicrons(die_area.xMin()):.2f} Y={design.dbuToMicrons(die_area.yMin()):.2f} W={design.dbuToMicrons(die_area.getWidth()):.2f} H={design.dbuToMicrons(die_area.getHeight()):.2f} um")
print("-" * 20)


# --- 3. I/O Pin Placement ---
print("\n--- I/O Pin Placement ---")
# Get the IOPlacer tool instance
io_placer = design.getIOPlacer()
if not io_placer:
    print("Error: IOPlacer tool not initialized.")
    exit()

# Get the parameters object for IOPlacer to configure it
io_params = io_placer.getParameters()

# Set minimum distance between pins. 0 is often used initially.
# While 0 is requested, a small non-zero value might be better practice in production.
min_io_dist_um = 0.0
io_params.setMinDistance(design.micronToDBU(min_io_dist_um))
print(f"Set minimum IO pin distance to {min_io_dist_um} um.")

# Add metal layers for horizontal (M8) and vertical (M9) pin placement as requested
tech = design.getTech() # Re-get tech if needed
metal8 = tech.findLayer("metal8")
metal9 = tech.findLayer("metal9")

layers_set = False
if metal8:
    # The first layer added is often considered the primary horizontal layer
    io_placer.addHorLayer(metal8)
    print(f"Added {metal8.getName()} for horizontal IO placement.")
    layers_set = True
else:
    print("Warning: metal8 layer not found. Cannot set for horizontal IO placement.")

if metal9:
    # The first layer added is often considered the primary vertical layer
    io_placer.addVerLayer(metal9)
    print(f"Added {metal9.getName()} for vertical IO placement.")
    layers_set = True
else:
    print("Warning: metal9 layer not found. Cannot set for vertical IO placement.")

# Run IO placement (using annealing algorithm by default)
# The 'True' parameter typically enables random mode or seed initialization.
# Ensure necessary layers are set before running, otherwise it will likely fail or do nothing.
if layers_set:
    print("Running I/O Pin Placement...")
    io_placer.runAnnealing(True) # True often indicates using randomization
    print("I/O Pin Placement finished.")
else:
     print("Warning: No metal layers set for IO placement. Skipping IO Placement.")
print("-" * 20)


# --- 4. Macro Placement ---
print("\n--- Macro Placement ---")
# Identify macro blocks. Macros are instances whose master is a block,
# as opposed to standard cells whose master is a stdCell.
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster() and inst.getMaster().isBlock()]

if len(macros) > 0:
    print(f"Found {len(macros)} macros to place.")
    # Get the MacroPlacer tool instance
    macro_placer = design.getMacroPlacer()
    if not macro_placer:
        print("Error: MacroPlacer tool not initialized.")
        exit()

    # Use the calculated core area as the fence for macro placement
    block = design.getBlock() # Re-get block to be safe if needed
    core = block.getCoreArea() # Get the actual core area after floorplanning (coordinates are in DBU)

    # Define macro placement parameters based on prompt
    macro_halo_um = 5.0 # Halo region around each macro (5 um as requested)
    macro_halo_dbu = design.micronToDBU(macro_halo_um)

    # The minimum spacing between macros (5um) is often achieved through the halo
    # setting and macro legalization within the macro placer or detailed placer.

    # Run macro placement within the core area fence.
    # The 'place' method requires the fence coordinates in DBU.
    # The core area boundary points (xMin, yMin, xMax, yMax) are already in DBU.
    print("Running Macro Placement...")
    macro_placer.place(
        num_threads = 4,          # Use an appropriate number of threads
        max_num_macro = len(macros), # Attempt to place all identified macros
        min_num_macro = len(macros), # Require placement of all identified macros
        max_num_inst = 0,         # Do not place standard cells in this step
        min_num_inst = 0,         # Ensure no standard cells are placed here
        halo_width = macro_halo_dbu, # Halo size in DBU
        halo_height = macro_halo_dbu,# Halo size in DBU
        # Define the fence using the core area calculated during floorplanning
        fence_lx = core.xMin(),   # Core lower-left X in DBU
        fence_ly = core.yMin(),   # Core lower-left Y in DBU
        fence_ux = core.xMax(),   # Core upper-right X in DBU
        fence_uy = core.yMax(),   # Core upper-right Y in DBU
        # Add other essential parameters with reasonable defaults if needed by the API.
        # These parameters influence the cost function.
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        fence_weight = 10.0
    )
    print("Macro Placement finished.")
else:
    print("No macros found in the design. Skipping Macro Placement.")
print("-" * 20)


# --- 5. Standard Cell Global Placement ---
print("\n--- Standard Cell Global Placement ---")
# Get the Global Placer tool instance (RePlAce)
gpl = design.getReplace()
if not gpl:
    print("Error: RePlAce tool not initialized.")
    exit()

# Set placement modes
# Set routability driven mode - helps address congestion early
gpl.setRoutabilityDrivenMode(True)
# Set timing driven mode if timing constraints (SDC) are loaded and valid.
# gpl.setTimingDrivenMode(True) # Uncomment this line if SDC is loaded

# Set uniform target density mode (common approach)
gpl.setUniformTargetDensityMode(True)

# Set the target utilization (density) for standard cells (35%)
# This should match or be close to the utilization used in floorplanning
gpl.setTargetDensity(target_utilization) # Using the variable from floorplanning

# The prompt's request for 10 iterations was for the *Global Router*, not Global Placer.
# Removing incorrect Global Placer iteration setting.
# gpl.setInitialPlaceMaxIter(10) # REMOVED based on prompt clarification

# Set initial density penalty factor (a common starting value)
gpl.setInitDensityPenalityFactor(0.05)

# Run initial placement (analytical or simplified)
print("Running Initial Placement (RePlAce)...")
gpl.doInitialPlace(threads = 4) # Use an appropriate number of threads
print("Initial Placement finished.")

# Run Nesterov placement (the main global placement step)
print("Running Nesterov Placement (RePlAce)...")
# The number of iterations for Nesterov placement is typically controlled
# internally or via advanced parameters not exposed by a simple 'doNesterovPlace'.
gpl.doNesterovPlace(threads = 4) # Use an appropriate number of threads
print("Nesterov Placement finished.")

# Reset placer state - good practice before subsequent steps or detailed reporting
gpl.reset()
print("-" * 20)


# --- 6. Standard Cell Detailed Placement ---
print("\n--- Standard Cell Detailed Placement ---")
# Get the Detailed Placer tool instance (OpenDP)
dp = design.getOpendp()
if not dp:
    print("Error: OpenDP tool not initialized.")
    exit()

# Remove existing filler cells before detailed placement if any were inserted earlier.
# This allows the detailed placer to freely move standard cells for legalization.
# Fillers are typically re-inserted after detailed placement, and often after routing.
print("Removing existing filler cells...")
dp.removeFillers()
print("Filler cells removed.")

# Set maximum displacement for detailed placement to 0 um in both x and y as requested.
# According to OpenDP API, maximum displacement is specified in *sites*.
# Convert the requested 0 um displacement to DBU, then divide by the site dimensions
# to get the displacement in sites.

max_disp_x_um = 0.0
max_disp_y_um = 0.0

# Convert micron displacement to DBU
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

# Check for valid site dimensions before division
if site_width_dbu <= 0 or site_height_dbu <= 0:
     print("Error: Standard cell site dimensions are zero or negative. Cannot calculate displacement in sites for detailed placement.")
     exit()

# Convert DBU displacement to sites using the standard cell site dimensions.
# Integer division is used as displacement is in integer sites.
# For 0 um displacement (0 DBU), this correctly results in 0 sites.
max_disp_x_sites = int(max_disp_x_dbu / site_width_dbu)
max_disp_y_sites = int(max_disp_y_dbu / site_height_dbu)

print(f"Requested max displacement: {max_disp_x_um} um (X), {max_disp_y_um} um (Y)")
print(f"Calculated max displacement in sites: {max_disp_x_sites} (X), {max_disp_y_sites} (Y)")


# Run detailed placement
# Parameters: max_displacement_x (sites), max_displacement_y (sites), debug_file_path, check_macro_halo
print(f"Running Detailed Placement with max displacement {max_disp_x_sites} sites...")
# Pass the calculated displacement in sites to the detailedPlacement function.
dp.detailedPlacement(max_disp_x_sites, max_disp_y_sites, "", False) # "" for no debug file, False for no macro halo check
print("Detailed Placement finished.")
print("-" * 20)


# --- 7. Global Routing (Setting Iterations as Requested) ---
# The prompt requested setting Global Router iterations.
# While Global Routing typically occurs after all placement, the prompt asks
# for the setting to be included in this script. We will perform a global route
# step here with the specified iteration count.
print("\n--- Global Routing (Setting Iterations) ---")
# Get the Global Router tool instance (Grt)
grt_tool = design.getGlobalRouter()
if not grt_tool:
    print("Error: Global Router tool not initialized.")
    exit()

# Set the number of iterations for the global router as requested (10 times).
global_router_iterations = 10

# Define other minimal required parameters for globalRoute.
# These might depend on the specific build/version, but tile size and grid origin are common.
# Using sensible defaults or values derived from the floorplan.
block = design.getBlock()
core_area = block.getCoreArea() # Get core area in DBU

# Use core lower-left as grid origin
grid_origin_x_dbu = core_area.xMin()
grid_origin_y_dbu = core_area.yMin()
# Choose a suitable tile size based on the technology or design scale.
# A common value might be 20-100 site widths. Using 50 um as an example.
tile_size_um = 50.0
tile_size_dbu = design.micronToDBU(tile_size_um)

print(f"Running Global Routing with {global_router_iterations} iterations...")
# Perform global routing. This populates the design with global routes,
# which can be used for congestion analysis or as input for detailed routing.
# It requires parameters like grid definition and iteration count.
grt_tool.globalRoute(
    grid_origin_x = grid_origin_x_dbu,
    grid_origin_y = grid_origin_y_dbu,
    tile_size = tile_size_dbu,
    gcells_per_pass = 2, # Common setting
    iterations = global_router_iterations, # Set iterations as requested
    allow_overflow = True # Often allows overflow in initial global routing passes
)
print(f"Global Routing finished with {global_router_iterations} iterations.")
print("-" * 20)


# --- 8. Output ---
# Dump the DEF file after placement (and global routing) as requested
output_def_file = "placement.def" # Still name it placement.def as requested
print(f"\n--- Output ---")
print(f"Dumping DEF file: {output_def_file}")
design.writeDef(output_def_file)
print("DEF file dumped successfully.")
print("-" * 20)

print("\nPlacement and partial Routing flow completed.")

# Note: This script performs placement and a global route step.
# A full flow would typically include Power Distribution Network (PDN) generation
# before placement, Clock Tree Synthesis (CTS) after global placement,
# and Detailed Routing after global routing. Filler cell insertion often happens
# before detailed routing or after detailed placement if no routing is performed.