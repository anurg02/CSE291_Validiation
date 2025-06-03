import odb
import pdn
import drt
import openroad as ord
from openroad import Tech, Design, Timing, Floorplan, IOPlacer, MacroPlacer, Replace, OpenDP, TritonCts, TritonRoute, GlobalRouter
from pathlib import Path
import traceback

# --- Configuration ---
# Paths to library and design files
# Assuming the structure is ./scripts/this_script.py
# and design files are in ../Design/
libDir = Path("../Design/nangate45/lib")
lefDir = Path("../Design/nangate45/lef")
designDir = Path("../Design/")
# The prompt assumes a Verilog netlist and mentions "gcd" in the Gemini script's comments
# Let's use a placeholder name derived from the prompt's context.
# If the netlist is generated from synthesis of "gcd", a common name might be "gcd_netlist.v"
# The prompt says "Given a verilog-described netlist...".
# Let's assume the netlist file name is based on the top module name.
design_top_module_name = "gcd"
design_netlist_file = designDir / f"{design_top_module_name}.v" # Assuming netlist is named after top module

# Clock configuration
clock_period_ns = 40.0
clock_port_name = "clk"
clock_name = "core_clock"

# Floorplanning configuration
floorplan_utilization = 0.45
# The prompt does not specify aspect ratio, using 1.0 (square core) as a reasonable default
floorplan_aspect_ratio = 1.0
floorplan_margin_um = 12.0
# Assuming a site name based on common examples for nangate45
site_name = "FreePDK45_38x28_10R_NP_162NW_34O"

# I/O Pin Placement configuration
io_hor_layer = "metal8"
io_ver_layer = "metal9"

# Macro Placement configuration
# Macro spacing is typically handled by halo and placement algorithm constraints.
# The halo definition is used to keep standard cells away from macros.
# A value of 5um is requested for halo.
macro_halo_um = 5.0
# Macro fence region
macro_fence_lx_um = 32.0
macro_fence_ly_um = 32.0
macro_fence_ux_um = 55.0
macro_fence_uy_um = 60.0
# Macro snap layer is not explicitly requested, but often pins are snapped.
# The Gemini script assumed metal4. Let's keep this assumption if needed by the placer.
# OpenROAD's macro placer snap_layer parameter often takes a layer *level*, not name.
# We will find the layer level later.
macro_snap_layer_name = "metal4"


# Placement configuration
# The prompt says "Set the iteration of the global router as 30 times", but this parameter
# usually applies to the global *placer* iterations in OpenROAD's RePlAce.
# Assuming this means global placer iterations.
global_place_iterations = 30
detailed_place_max_disp_x_um = 0.5
detailed_place_max_disp_y_um = 0.5

# RC values (set before CTS and routing)
unit_resistance = 0.03574
unit_capacitance = 0.07516

# CTS configuration
cts_buffer_cell = "BUF_X2"

# PDN Configuration
# Power/Ground net names - standard conventions
power_net_name = "VDD"
ground_net_name = "VSS"

# Standard cell grid (Core domain)
std_cell_ring_layers = ["metal7", "metal8"] # M7 and M8 rings
std_cell_ring_width_um = 5.0
std_cell_ring_spacing_um = 5.0

std_cell_strap_m1_width_um = 0.07 # M1 straps
std_cell_strap_m4_width_um = 1.2 # M4 straps
std_cell_strap_m4_spacing_um = 1.2
std_cell_strap_m4_pitch_um = 6.0
std_cell_strap_m7_width_um = 1.4 # M7 straps
std_cell_strap_m7_spacing_um = 1.4
std_cell_strap_m7_pitch_um = 10.8
std_cell_strap_m8_width_um = 1.4 # M8 straps
std_cell_strap_m8_spacing_um = 1.4
std_cell_strap_m8_pitch_um = 10.8

# Macro grid (within macro fence area)
# Apply only if macros exist
macro_grid_layers = ["metal5", "metal6"] # M5 and M6 straps/rings for macros
# The prompt says "set the width and spacing of both M5 and M6 grids to 1.2 um, and set the pitch to 6 um."
# This implies width=1.2, spacing=1.2, pitch=6 for straps and rings on M5/M6 within the macro grid area.
macro_grid_width_um = 1.2
macro_grid_spacing_um = 1.2
macro_grid_pitch_um = 6.0

# Via connection pitch between grids (0 um interpreted as default/tech minimum)
via_cut_pitch_um = 0.0
pdn_offset_um = 0.0 # Offset for rings and straps

# Routing configuration
global_route_min_layer = "metal1"
global_route_max_layer = "metal7" # Based on prompt's layer range for M7/M8 rings/straps

# --- Helper Function to write DEF ---
def write_def(design, filename):
    "Writes the current design state to a DEF file."
    try:
        design.writeDef(filename)
        print(f"Successfully wrote {filename}")
    except Exception as e:
        print(f"Error writing DEF file {filename}: {e}")
        traceback.print_exc()

# --- Initialization ---
print("--- Initializing OpenROAD ---")
# Initialize OpenROAD objects
tech = Tech()
design = Design(tech)
db = ord.get_db() # Get the underlying OpenDB database

# Read technology files
print(f"Reading technology LEF files from {lefDir.as_posix()}")
techLefFiles = lefDir.glob("*.tech.lef")
for techLefFile in techLefFiles:
    tech.readLef(techLefFile.as_posix())

# Read library LEF files
print(f"Reading library LEF files from {lefDir.as_posix()}")
lefFiles = lefDir.glob('*.lef')
for lefFile in lefFiles:
    tech.readLef(lefFile.as_posix())

# Read liberty timing libraries
print(f"Reading liberty files from {libDir.as_posix()}")
libFiles = libDir.glob("*.lib")
for libFile in libFiles:
    tech.readLiberty(libFile.as_posix())

# Create design and read Verilog netlist
print(f"Reading Verilog netlist {design_netlist_file.as_posix()}")
if not design_netlist_file.exists():
    print(f"Error: Netlist file not found at {design_netlist_file.as_posix()}")
    exit(1)
design.readVerilog(design_netlist_file.as_posix())

# Link design to libraries
print(f"Linking design top module: {design_top_module_name}")
design.link(design_top_module_name)

block = design.getBlock()
tech_db = db.getTech()

# --- Clock Setup ---
print("\n--- Setting up Clock ---")
# Create clock signal on the specified port with the given period and name
try:
    design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
    # Propagate the clock signal for timing analysis (needed for timing-driven stages)
    # Note: Timing setup might need more details depending on the design (input delays, output loads, etc.)
    # For this script, we just set the propagated clock.
    design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")
    print(f"Clock '{clock_name}' created on port '{clock_port_name}' with period {clock_period_ns} ns.")
except Exception as e:
    print(f"Error setting up clock: {e}")
    # Continue as floorplanning/placement might still work, but subsequent timing stages will fail.

# --- Floorplanning ---
print("\n--- Running Floorplanning ---")
floorplan = design.getFloorplan()
site = floorplan.findSite(site_name)
if not site:
    print(f"Error: Site '{site_name}' not found in LEF files.")
    # Try to find a default site
    sites = tech_db.getSites()
    if sites:
        site = sites[0]
        print(f"Using first found site: {site.getName()}")
    else:
        print("Error: No sites found in LEF files. Cannot perform floorplanning.")
        exit(1)

# Convert floorplan margin to DBU
floorplan_margin_dbu = design.micronToDBU(floorplan_margin_um)

try:
    # Initialize floorplan with utilization, aspect ratio, and margins
    floorplan.initFloorplan(
        utilization = floorplan_utilization,
        aspectRatio = floorplan_aspect_ratio,
        coreMargin = floorplan_margin_dbu, # Applies margin to all sides
        site = site
    )
    print(f"Floorplan initialized with utilization {floorplan_utilization}, aspect ratio {floorplan_aspect_ratio}, core margin {floorplan_margin_um} um.")

    # Create routing tracks within the core area
    floorplan.makeTracks()
    print("Routing tracks created.")

    # Dump DEF after floorplanning
    write_def(design, "floorplanned.def")

except Exception as e:
    print(f"Error during floorplanning: {e}")
    traceback.print_exc()
    # Attempt to continue, but placement/routing might fail if floorplan is invalid.

# --- I/O Pin Placement ---
print("\n--- Running I/O Pin Placement ---")
io_placer = design.getIOPlacer()
io_placer_params = io_placer.getParameters()

# Find requested I/O layers
hor_layer_obj = tech_db.findLayer(io_hor_layer)
ver_layer_obj = tech_db.findLayer(io_ver_layer)

if not hor_layer_obj or not ver_layer_obj:
    print(f"Error: Cannot find I/O pin layers '{io_hor_layer}' or '{io_ver_layer}'. Skipping I/O placement.")
else:
    try:
        io_placer_params.setRandSeed(42) # Use a fixed seed for reproducibility
        # The prompt doesn't specify minimum distance, using 0 as default
        io_placer_params.setMinDistanceInTracks(False) # Specify minimum distance in database units
        io_placer_params.setMinDistance(design.micronToDBU(0))
        io_placer_params.setCornerAvoidance(design.micronToDBU(0)) # No specific corner avoidance requested

        # Add horizontal and vertical layers for pin placement
        io_placer.addHorLayer(hor_layer_obj)
        io_placer.addVerLayer(ver_layer_obj)
        print(f"Configured I/O pin layers: Horizontal on {io_hor_layer}, Vertical on {io_ver_layer}.")

        # Run the annealing-based I/O placer
        # The runAnnealing(True) flag enables random mode which explores different solutions.
        io_placer.runAnnealing(True)
        print("I/O placement completed.")

        # Dump DEF after I/O placement
        write_def(design, "io_placed.def")

    except Exception as e:
        print(f"Error during I/O placement: {e}")
        traceback.print_exc()

# --- Macro Placement ---
print("\n--- Running Macro Placement ---")
# Identify macro instances (instances whose master is a block, not a standard cell)
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    print(f"Found {len(macros)} macro instances. Running macro placement.")
    mpl = design.getMacroPlacer()

    # Convert macro fence coordinates and halo to DBU
    fence_lx_dbu = design.micronToDBU(macro_fence_lx_um)
    fence_ly_dbu = design.micronToDBU(macro_fence_ly_um)
    fence_ux_dbu = design.micronToDBU(macro_fence_ux_um)
    fence_uy_dbu = design.micronToDBU(macro_fence_uy_um)
    macro_halo_dbu = design.micronToDBU(macro_halo_um)

    # Find macro snap layer level if requested
    macro_snap_layer = tech_db.findLayer(macro_snap_layer_name)
    macro_snap_layer_level = -1 # Default to no snap layer
    if macro_snap_layer:
        macro_snap_layer_level = macro_snap_layer.getRoutingLevel()
        print(f"Macros will snap to track grid of layer '{macro_snap_layer_name}' (level {macro_snap_layer_level}).")
    else:
         print(f"Warning: Macro snap layer '{macro_snap_layer_name}' not found. Macros will not snap to a specific layer grid.")


    try:
        # Run macro placement
        # Parameters often depend on the specific design and technology.
        # Using a set of common parameters and the requested ones.
        mpl.place(
            num_threads = 64, # Example thread count
            max_num_macro = len(macros),
            min_num_macro = 0,
            max_num_inst = 0, # Consider all standard cells during macro placement
            min_num_inst = 0,
            tolerance = 0.1,
            max_num_level = 2,
            coarsening_ratio = 10.0,
            large_net_threshold = 50,
            signature_net_threshold = 50,
            halo_width = macro_halo_um, # Set macro halo width in microns
            halo_height = macro_halo_um, # Set macro halo height in microns
            fence_lx = macro_fence_lx_um, # Set fence lower-left X in microns
            fence_ly = macro_fence_ly_um, # Set fence lower-left Y in microns
            fence_ux = macro_fence_ux_um, # Set fence upper-right X in microns
            fence_uy = macro_fence_uy_um, # Set fence upper-right Y in microns
            area_weight = 0.1,
            outline_weight = 100.0,
            wirelength_weight = 100.0,
            guidance_weight = 10.0,
            fence_weight = 10.0,
            boundary_weight = 50.0,
            notch_weight = 10.0,
            macro_blockage_weight = 10.0,
            pin_access_th = 0.0, # Pin access threshold
            target_util = floorplan_utilization, # Use floorplan utilization as a target
            target_dead_space = 0.05, # Target dead space percentage
            min_ar = 0.33, # Minimum aspect ratio for macro clusters
            snap_layer = macro_snap_layer_level, # Snap macro origins to specified layer's track grid (level)
            bus_planning_flag = False, # Disable bus planning
            report_directory = "" # Do not generate report directory
        )
        print("Macro placement completed.")

        # Dump DEF after macro placement
        write_def(design, "macro_placed.def")

    except Exception as e:
        print(f"Error during macro placement: {e}")
        traceback.print_exc()

else:
    print("No macro instances found. Skipping macro placement.")

# --- Global Placement ---
print("\n--- Running Global Placement ---")
gpl = design.getReplace() # RePlAce is the global placer

try:
    gpl.setTimingDrivenMode(False) # Disable timing-driven mode unless needed later
    gpl.setRoutabilityDrivenMode(True) # Enable routability-driven mode
    gpl.setUniformTargetDensityMode(True) # Use uniform target density across the core

    # Set the number of iterations for the initial placement phase as requested
    # This corresponds to the 'global router iterations' in the prompt, interpreted as global *placer* iterations.
    gpl.setInitialPlaceMaxIter(global_place_iterations)
    print(f"Global placer initial iterations set to {global_place_iterations}.")

    gpl.setInitDensityPenalityFactor(0.05) # Initial density penalty
    # Run initial and Nesterov-based placement phases
    gpl.doInitialPlace(threads = 4) # Example thread count
    gpl.doNesterovPlace(threads = 4) # Example thread count
    # gpl.reset() # Resetting might clear placement results depending on API version; keep results

    print("Global placement completed.")

    # Dump DEF after global placement
    write_def(design, "global_placed.def")

except Exception as e:
    print(f"Error during global placement: {e}")
    traceback.print_exc()

# --- Detailed Placement (Before CTS) ---
print("\n--- Running Detailed Placement (Before CTS) ---")
opendp = design.getOpendp()

try:
    # Convert maximum displacement to DBU
    max_disp_x_dbu = design.micronToDBU(detailed_place_max_disp_x_um)
    max_disp_y_dbu = design.micronToDBU(detailed_place_max_disp_y_um)

    # It's good practice to remove any potential existing filler cells before detailed placement
    # (though they shouldn't exist yet if flow is sequential).
    opendp.removeFillers()
    print("Removed any existing filler cells.")

    # Perform detailed placement within the maximum displacement limits
    # The last two parameters are "padding" and "inPlace", using defaults/common values
    opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
    print(f"Detailed placement (before CTS) completed with max displacement {detailed_place_max_disp_x_um} um (X), {detailed_place_max_disp_y_um} um (Y).")

    # Dump DEF after detailed placement (before CTS)
    write_def(design, "detailed_placed_before_cts.def")

except Exception as e:
    print(f"Error during detailed placement (before CTS): {e}")
    traceback.print_exc()

# --- Set RC values ---
print("\n--- Setting Wire RC Values ---")
# Set unit resistance and capacitance for clock nets
try:
    design.evalTclString(f"set_wire_rc -clock -resistance {unit_resistance} -capacitance {unit_capacitance}")
    print(f"Set clock wire RC: R={unit_resistance}, C={unit_capacitance}")
    # Set unit resistance and capacitance for signal nets
    design.evalTclString(f"set_wire_rc -signal -resistance {unit_resistance} -capacitance {unit_capacitance}")
    print(f"Set signal wire RC: R={unit_resistance}, C={unit_capacitance}")
except Exception as e:
    print(f"Error setting wire RC values: {e}")
    traceback.print_exc()


# --- Power Delivery Network (PDN) Construction ---
print("\n--- Constructing Power Delivery Network (PDN) ---")
pdngen = design.getPdnGen()

try:
    # Ensure power/ground nets are marked as special
    power_net = block.findNet(power_net_name)
    ground_net = block.findNet(ground_net_name)

    # Create VDD/VSS nets if they don't exist (common in synthesized netlists)
    if power_net is None:
        print(f"Power net '{power_net_name}' not found. Creating it.")
        power_net = odb.dbNet_create(block, power_net_name)
        power_net.setSigType("POWER")
    if ground_net is None:
        print(f"Ground net '{ground_net_name}' not found. Creating it.")
        ground_net = odb.dbNet_create(block, ground_net_name)
        ground_net.setSigType("GROUND")

    # Mark nets as special
    power_net.setSpecial()
    ground_net.setSpecial()
    print(f"Power net '{power_net_name}' and ground net '{ground_net_name}' marked as special.")

    # Connect power pins to global nets
    # This connects all VDD/VSS related pins on instances to the global VDD/VSS nets
    print(f"Connecting power pins to global nets '{power_net_name}' and '{ground_net_name}'.")
    # Assuming standard VDD/VSS pin names, adjust pinPattern if needed
    block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "VCC|VDD.*", net = power_net, do_connect = True)
    block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "VSS|GND|VSS.*|GND.*", net = ground_net, do_connect = True)
    # Apply the global connections
    block.globalConnect()
    print("Global connections applied.")

    # Set up core power domain
    # Check if the core domain already exists
    core_domain = pdngen.findDomain("Core")
    if not core_domain:
        print("Core domain not found. Setting it up.")
        pdngen.setCoreDomain(power = power_net, ground = ground_net)
        core_domain = pdngen.findDomain("Core")[0] # Retrieve the created domain
    else:
         core_domain = core_domain[0] # Get the existing domain object
         print("Core domain found.")

    # Get metal layers by name and level
    metal_layers = {}
    for i in range(1, 10): # Assuming layers metal1 through metal9 might exist
        layer_name = f"metal{i}"
        layer_obj = tech_db.findLayer(layer_name)
        if layer_obj:
            metal_layers[layer_name] = layer_obj
            # print(f"Found layer: {layer_name} (level {layer_obj.getRoutingLevel()})")
        else:
            print(f"Warning: Layer '{layer_name}' not found.")

    # Check required layers exist
    required_layers = set(std_cell_ring_layers + [f"metal{i}" for i in [1, 4, 7, 8]] + macro_grid_layers)
    for layer_name in required_layers:
        if layer_name not in metal_layers:
            print(f"Error: Required PDN layer '{layer_name}' not found in technology LEF. Cannot build PDN.")
            # Attempt to proceed, but PDN generation will likely fail.
            # In a real flow, you might exit or handle specific layers missing.

    # Convert PDN dimensions to DBU
    std_cell_ring_width_dbu = design.micronToDBU(std_cell_ring_width_um)
    std_cell_ring_spacing_dbu = design.micronToDBU(std_cell_ring_spacing_um)
    std_cell_strap_m1_width_dbu = design.micronToDBU(std_cell_strap_m1_width_um)
    std_cell_strap_m4_width_dbu = design.micronToDBU(std_cell_strap_m4_width_um)
    std_cell_strap_m4_spacing_dbu = design.micronToDBU(std_cell_strap_m4_spacing_um)
    std_cell_strap_m4_pitch_dbu = design.micronToDBU(std_cell_strap_m4_pitch_um)
    std_cell_strap_m7_width_dbu = design.micronToDBU(std_cell_strap_m7_width_um)
    std_cell_strap_m7_spacing_dbu = design.micronToDBU(std_cell_strap_m7_spacing_um)
    std_cell_strap_m7_pitch_dbu = design.micronToDBU(std_cell_strap_m7_pitch_um)
    std_cell_strap_m8_width_dbu = design.micronToDBU(std_cell_strap_m8_width_um)
    std_cell_strap_m8_spacing_dbu = design.micronToDBU(std_cell_strap_m8_spacing_um)
    std_cell_strap_m8_pitch_dbu = design.micronToDBU(std_cell_strap_m8_pitch_um)

    macro_grid_width_dbu = design.micronToDBU(macro_grid_width_um)
    macro_grid_spacing_dbu = design.micronToDBU(macro_grid_spacing_um)
    macro_grid_pitch_dbu = design.micronToDBU(macro_grid_pitch_um)

    pdn_offset_dbu = design.micronToDBU(pdn_offset_um)
    via_cut_pitch_dbu = design.micronToDBU(via_cut_pitch_um)

    # Create the main core grid structure for standard cells
    print("Creating core grid for standard cells.")
    core_grid_name = "core_grid"
    # Find any previously created core grid to avoid duplicates
    existing_core_grid = pdngen.findGrid(core_grid_name)
    if existing_core_grid:
        print(f"Core grid '{core_grid_name}' already exists. Reusing it.")
        core_grid = existing_core_grid[0]
    else:
        print(f"Creating new core grid '{core_grid_name}'.")
        # Exclude macro halo regions from the standard cell grid area if macros exist
        halo_boundaries_dbu = []
        if len(macros) > 0:
             macro_halo_dbu = design.micronToDBU(macro_halo_um)
             for macro_inst in macros:
                 inst_bbox = macro_inst.getBBox()
                 # Create exclusion rectangle (bbox + halo) in DBU
                 excl_lx = inst_bbox.getBox().xMin() - macro_halo_dbu
                 excl_ly = inst_bbox.getBox().yMin() - macro_halo_dbu
                 excl_ux = inst_bbox.getBox().xMax() + macro_halo_dbu
                 excl_uy = inst_bbox.getBox().yMax() + macro_halo_dbu
                 halo_boundaries_dbu.append(odb.Rect(excl_lx, excl_ly, excl_ux, excl_uy))
             print(f"Excluding {len(macros)} macro halo regions from core grid.")

        pdngen.makeCoreGrid(domain = core_domain,
            name = core_grid_name,
            starts_with = pdn.GROUND,  # Start with ground net
            # halo parameter expects a list of Rects in DBU
            halo = halo_boundaries_dbu,
            pin_layers = [], # No specific pin layers for core grid creation
            generate_obstructions = [], # Do not generate obstructions by default
            powercell = None, # No power cell definition
            powercontrol = None, # No power control definition
            powercontrolnetwork = "STAR") # Use STAR network for power control

        # Get the created core grid
        core_grid = pdngen.findGrid(core_grid_name)[0]
        print(f"Core grid '{core_grid_name}' created.")

    # Add standard cell rings on M7 and M8
    if metal_layers.get("metal7") and metal_layers.get("metal8"):
        print("Adding standard cell rings on metal7 and metal8.")
        pdngen.makeRing(grid = core_grid,
            layer0 = metal_layers["metal7"], width0 = std_cell_ring_width_dbu, spacing0 = std_cell_ring_spacing_dbu,
            layer1 = metal_layers["metal8"], width1 = std_cell_ring_width_dbu, spacing1 = std_cell_ring_spacing_dbu,
            starts_with = pdn.GRID, # Align with grid pattern
            offset = [pdn_offset_dbu] * 4, # Offset from boundary (left, bottom, right, top)
            pad_offset = [pdn_offset_dbu] * 4, # Pad offset (usually same as offset)
            extend = False, # Do not extend rings beyond boundary
            pad_pin_layers = [], # No connections to pads from rings
            nets = [], # Apply to all nets in grid (VDD/VSS)
            allow_out_of_die = True) # Rings can extend out of the die if necessary
        print("Standard cell rings added.")
    else:
        print("Warning: Cannot add standard cell rings. Missing metal7 or metal8.")


    # Add standard cell straps
    print("Adding standard cell straps.")
    # M1 followpin straps (horizontal, often parallel to standard cell rows)
    if metal_layers.get("metal1"):
        pdngen.makeFollowpin(grid = core_grid,
            layer = metal_layers["metal1"],
            width = std_cell_strap_m1_width_dbu,
            extend = pdn.CORE) # Extend straps within the core area
        print("M1 followpin straps added.")
    else:
        print("Warning: Cannot add M1 straps. Missing metal1.")

    # M4 straps (vertical)
    if metal_layers.get("metal4"):
         pdngen.makeStrap(grid = core_grid,
            layer = metal_layers["metal4"],
            width = std_cell_strap_m4_width_dbu,
            spacing = std_cell_strap_m4_spacing_dbu,
            pitch = std_cell_strap_m4_pitch_dbu,
            offset = pdn_offset_dbu,
            number_of_straps = 0, # Auto-calculate number based on pitch
            snap = True, # Snap to grid based on pitch/offset
            starts_with = pdn.GRID, # Start based on grid alignment
            extend = pdn.CORE, # Extend within the core area
            nets = []) # Apply to all nets in grid
         print("M4 straps added.")
    else:
         print("Warning: Cannot add M4 straps. Missing metal4.")

    # M7 straps (horizontal)
    if metal_layers.get("metal7"):
        pdngen.makeStrap(grid = core_grid,
            layer = metal_layers["metal7"],
            width = std_cell_strap_m7_width_dbu,
            spacing = std_cell_strap_m7_spacing_dbu,
            pitch = std_cell_strap_m7_pitch_dbu,
            offset = pdn_offset_dbu,
            number_of_straps = 0,
            snap = True,
            starts_with = pdn.GRID,
            extend = pdn.CORE, # Extend within the core area
            nets = [])
        print("M7 straps added.")
    else:
        print("Warning: Cannot add M7 straps. Missing metal7.")

    # M8 straps (vertical) - Note: Prompt inconsistent, M8 is also a ring layer. Adding straps as requested.
    if metal_layers.get("metal8"):
        pdngen.makeStrap(grid = core_grid,
            layer = metal_layers["metal8"],
            width = std_cell_strap_m8_width_dbu,
            spacing = std_cell_strap_m8_spacing_dbu,
            pitch = std_cell_strap_m8_pitch_dbu,
            offset = pdn_offset_dbu,
            number_of_straps = 0,
            snap = True,
            starts_with = pdn.GRID,
            extend = pdn.CORE, # Extend within the core area
            nets = [])
        print("M8 straps added.")
    else:
        print("Warning: Cannot add M8 straps. Missing metal8.")

    # Create power grid for macro blocks (if they exist) within the fence area
    if len(macros) > 0:
        print("\nCreating macro grid within macro fence area.")
        macro_grid_name = "macro_grid"
        existing_macro_grid = pdngen.findGrid(macro_grid_name)
        if existing_macro_grid:
            print(f"Macro grid '{macro_grid_name}' already exists. Reusing it.")
            macro_grid = existing_macro_grid[0]
        else:
             print(f"Creating new macro grid '{macro_grid_name}' within the macro fence region.")
             # Create a region corresponding to the macro fence
             fence_region = odb.Rect(fence_lx_dbu, fence_ly_dbu, fence_ux_dbu, fence_uy_dbu)
             pdngen.makeInstanceGrid(domain = core_domain, # Assume macros are in core domain
                 name = macro_grid_name,
                 starts_with = pdn.GROUND, # Start with ground net
                 # Apply this grid only within the macro fence region
                 area = fence_region,
                 # No halo needed here, as this grid is specifically for the macro area
                 halo = [],
                 pg_pins_to_boundary = True,  # Connect power/ground pins to the macro boundary
                 default_grid = False, # Not the default grid
                 generate_obstructions = [],
                 is_bump = False) # Not a bump grid

             # Get the macro instance grid
             macro_grid = pdngen.findGrid(macro_grid_name)[0]
             print(f"Macro grid '{macro_grid_name}' created for fence region.")


        # Add macro rings on M5 and M6 (using macro grid parameters)
        if metal_layers.get("metal5") and metal_layers.get("metal6"):
             print("Adding macro rings on metal5 and metal6.")
             pdngen.makeRing(grid = macro_grid,
                layer0 = metal_layers["metal5"], width0 = macro_grid_width_dbu, spacing0 = macro_grid_spacing_dbu,
                layer1 = metal_layers["metal6"], width1 = macro_grid_width_dbu, spacing1 = macro_grid_spacing_dbu,
                starts_with = pdn.GRID,
                offset = [pdn_offset_dbu] * 4,
                pad_offset = [pdn_offset_dbu] * 4,
                extend = False, # Rings within the macro grid area
                pad_pin_layers = [],
                nets = [])
             print("Macro rings added.")
        else:
             print("Warning: Cannot add macro rings. Missing metal5 or metal6.")

        # Add macro straps on M5 and M6 (using macro grid parameters)
        if metal_layers.get("metal5"):
             print("Adding macro M5 straps.")
             pdngen.makeStrap(grid = macro_grid,
                layer = metal_layers["metal5"],
                width = macro_grid_width_dbu,
                spacing = macro_grid_spacing_dbu,
                pitch = macro_grid_pitch_dbu,
                offset = pdn_offset_dbu,
                number_of_straps = 0,
                snap = True,
                starts_with = pdn.GRID,
                extend = pdn.CORE, # Extend within the macro grid area
                nets = [])
             print("Macro M5 straps added.")
        else:
             print("Warning: Cannot add macro M5 straps. Missing metal5.")

        if metal_layers.get("metal6"):
            print("Adding macro M6 straps.")
            pdngen.makeStrap(grid = macro_grid,
                layer = metal_layers["metal6"],
                width = macro_grid_width_dbu,
                spacing = macro_grid_spacing_dbu,
                pitch = macro_grid_pitch_dbu,
                offset = pdn_offset_dbu,
                number_of_straps = 0,
                snap = True,
                starts_with = pdn.GRID,
                extend = pdn.CORE, # Extend within the macro grid area
                nets = [])
            print("Macro M6 straps added.")
        else:
            print("Warning: Cannot add macro M6 straps. Missing metal6.")


        # Create via connections for macro grid to connect to core grid and within itself
        print("Adding via connections for macro grid.")
        # M4 (core strap layer) to M5 (macro layer)
        if metal_layers.get("metal4") and metal_layers.get("metal5"):
            pdngen.makeConnect(grid = macro_grid, layer0 = metal_layers["metal4"], layer1 = metal_layers["metal5"],
                               cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
            print("Via connections: M4 to M5 added.")
        else:
            print("Warning: Cannot add M4-M5 via connections for macro grid. Missing metal4 or metal5.")

        # M5 (macro layer) to M6 (macro layer)
        if metal_layers.get("metal5") and metal_layers.get("metal6"):
             pdngen.makeConnect(grid = macro_grid, layer0 = metal_layers["metal5"], layer1 = metal_layers["metal6"],
                               cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
             print("Via connections: M5 to M6 added.")
        else:
             print("Warning: Cannot add M5-M6 via connections for macro grid. Missing metal5 or metal6.")

        # M6 (macro layer) to M7 (core strap/ring layer)
        if metal_layers.get("metal6") and metal_layers.get("metal7"):
            pdngen.makeConnect(grid = macro_grid, layer0 = metal_layers["metal6"], layer1 = metal_layers["metal7"],
                               cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
            print("Via connections: M6 to M7 added.")
        else:
            print("Warning: Cannot add M6-M7 via connections for macro grid. Missing metal6 or metal7.")

    else:
        print("No macros found. Skipping macro PDN construction.")


    # Create via connections for core grid (standard cells)
    print("Adding via connections for core grid.")
    # Connect M1 to M4
    if metal_layers.get("metal1") and metal_layers.get("metal4"):
        pdngen.makeConnect(grid = core_grid, layer0 = metal_layers["metal1"], layer1 = metal_layers["metal4"],
                           cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
        print("Via connections: M1 to M4 added.")
    else:
        print("Warning: Cannot add M1-M4 via connections for core grid. Missing metal1 or metal4.")

    # Connect M4 to M7
    if metal_layers.get("metal4") and metal_layers.get("metal7"):
        pdngen.makeConnect(grid = core_grid, layer0 = metal_layers["metal4"], layer1 = metal_layers["metal7"],
                           cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
        print("Via connections: M4 to M7 added.")
    else:
        print("Warning: Cannot add M4-M7 via connections for core grid. Missing metal4 or metal7.")

    # Connect M7 to M8 (for strap/ring connections)
    if metal_layers.get("metal7") and metal_layers.get("metal8"):
        pdngen.makeConnect(grid = core_grid, layer0 = metal_layers["metal7"], layer1 = metal_layers["metal8"],
                           cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
        print("Via connections: M7 to M8 added.")
    else:
         print("Warning: Cannot add M7-M8 via connections for core grid. Missing metal7 or metal8.")


    # Generate the final power delivery network shapes
    pdngen.checkSetup()  # Verify configuration
    print("PDN setup checked. Building grids...")
    pdngen.buildGrids(False)  # Build the power grid shapes
    print("Grids built. Writing to DB...")
    pdngen.writeToDb(True)  # Write power grid shapes to the design database
    pdngen.resetShapes()  # Reset temporary shapes used during build
    print("PDN construction completed.")

    # Dump DEF after PDN construction
    write_def(design, "pdn_constructed.def")

except Exception as e:
    print(f"Error during PDN construction: {e}")
    traceback.print_exc()


# --- Clock Tree Synthesis (CTS) ---
print("\n--- Running Clock Tree Synthesis (CTS) ---")
cts = design.getTritonCts()
cts_parms = cts.getParms()

try:
    # Set clock buffer cell(s)
    if not cts_buffer_cell:
        print("Warning: No CTS buffer cell specified. CTS might not run correctly.")
    else:
        cts.setBufferList(cts_buffer_cell)
        cts.setRootBuffer(cts_buffer_cell) # Often root buffer is the same or a larger version
        cts.setSinkBuffer(cts_buffer_cell) # Often sink buffer is the same or a smaller version
        print(f"Set CTS buffer cell(s) to '{cts_buffer_cell}'.")

    # Example: Set wire segment unit for CTS
    # A typical value is based on standard cell width or half row height.
    # Let's use a reasonable value based on 45nm process and common cell sizes.
    # If site is available, we could calculate based on site width.
    wire_segment_unit_um = 5.0 # Example value
    cts_parms.setWireSegmentUnit(design.micronToDBU(wire_segment_unit_um))
    print(f"Set CTS wire segment unit to {wire_segment_unit_um} um.")


    # Run CTS
    # Need to specify the clock net for CTS
    clock_nets = block.findNet(clock_name)
    if not clock_nets:
         print(f"Error: Clock net '{clock_name}' not found. Cannot run CTS.")
    else:
        # Pass the clock net object to runTritonCts
        cts.runTritonCts(clock_nets)
        print("CTS completed.")

        # Dump DEF after CTS
        write_def(design, "cts.def")

except Exception as e:
    print(f"Error during CTS: {e}")
    traceback.print_exc()

# --- Detailed Placement (After CTS) ---
print("\n--- Running Detailed Placement (After CTS) ---")
# Re-run detailed placement after CTS to fix any minor displacement caused by CTS buffer insertion.
opendp = design.getOpendp()

try:
    # Max displacement is the same as before CTS
    max_disp_x_dbu = design.micronToDBU(detailed_place_max_disp_x_um)
    max_disp_y_dbu = design.micronToDBU(detailed_place_max_disp_y_um)

    # Remove any filler cells inserted after the first detailed placement (if any were added prematurely)
    # or before inserting final fillers.
    opendp.removeFillers()
    print("Removed any existing filler cells before final detailed placement.")

    # Perform detailed placement
    opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
    print(f"Detailed placement (after CTS) completed with max displacement {detailed_place_max_disp_x_um} um (X), {detailed_place_max_disp_y_um} um (Y).")

    # Dump DEF after detailed placement (after CTS)
    write_def(design, "detailed_placed_after_cts.def")

except Exception as e:
    print(f"Error during detailed placement (after CTS): {e}")
    traceback.print_exc()

# --- Filler Insertion ---
print("\n--- Inserting Filler Cells ---")
opendp = design.getOpendp()
db = ord.get_db()

# Find CORE_SPACER masters in all libraries
filler_masters = list()
# Define a naming convention for filler cells
filler_cells_prefix = "FILLCELL_"
print(f"Searching for CORE_SPACER cells (prefix '{filler_cells_prefix}')")

try:
    for lib in db.getLibs():
        for master in lib.getMasters():
            if master.getType() == "CORE_SPACER":
                filler_masters.append(master)
                # print(f"Found filler master: {master.getName()} from library {lib.getName()}")

    if len(filler_masters) == 0:
        print("Warning: No CORE_SPACER cells found for filler insertion. Skipping filler placement.")
    else:
        print(f"Found {len(filler_masters)} CORE_SPACER masters. Performing filler placement.")
        # Perform filler placement
        opendp.fillerPlacement(filler_masters = filler_masters,
                                 prefix = filler_cells_prefix,
                                 verbose = False)
        print("Filler cell insertion completed.")

        # Dump DEF after filler insertion
        write_def(design, "filler_inserted.def")

except Exception as e:
    print(f"Error during filler insertion: {e}")
    traceback.print_exc()

# --- Global Routing ---
print("\n--- Running Global Routing ---")
grt = design.getGlobalRouter()

try:
    # Get routing layer levels
    signal_low_layer_obj = tech_db.findLayer(global_route_min_layer)
    signal_high_layer_obj = tech_db.findLayer(global_route_max_layer)

    if not signal_low_layer_obj or not signal_high_layer_obj:
        print(f"Error: Cannot find global routing layers '{global_route_min_layer}' or '{global_route_max_layer}'. Skipping global routing.")
    else:
        signal_low_layer_level = signal_low_layer_obj.getRoutingLevel()
        signal_high_layer_level = signal_high_layer_obj.getRoutingLevel()

        # Set routing layer ranges for signal and clock nets
        grt.setMinRoutingLayer(signal_low_layer_level)
        grt.setMaxRoutingLayer(signal_high_layer_level)
        # Usually clock uses a wider range or preferred layers, but prompt doesn't specify.
        # Using the same range for clock nets as signal nets here.
        grt.setMinLayerForClock(signal_low_layer_level)
        grt.setMaxLayerForClock(signal_high_layer_level)
        print(f"Global routing layer range: {global_route_min_layer} (level {signal_low_layer_level}) to {global_route_max_layer} (level {signal_high_layer_level}).")

        grt.setAdjustment(0.5) # Congestion adjustment factor - common starting point
        grt.setVerbose(True) # Enable verbose output

        # Run global routing (True indicates routing based on current placement)
        grt.globalRoute(True)
        print("Global routing completed.")

        # Dump DEF after global routing
        write_def(design, "global_routed.def")

except Exception as e:
    print(f"Error during global routing: {e}")
    traceback.print_exc()


# --- Detailed Routing ---
print("\n--- Running Detailed Routing ---")
drter = design.getTritonRoute()
dr_params = drt.ParamStruct()

try:
    # Set parameters for detailed routing
    # Many parameters exist; setting key ones and using defaults for others.
    dr_params.enableViaGen = True # Enable via generation
    dr_params.drouteEndIter = 1 # Number of detailed routing iterations (1 is common for a basic run)
    dr_params.orSeed = -1 # Random seed (-1 uses current time)
    # Set routing layer range by name (DRT takes names, GRT takes levels)
    dr_params.bottomRoutingLayer = global_route_min_layer
    dr_params.topRoutingLayer = global_route_max_layer
    dr_params.verbose = 1 # Verbosity level
    dr_params.cleanPatches = True # Clean up small patches
    dr_params.doPa = True # Perform post-route repair (e.g., wire spreading, via optimization)
    dr_params.singleStepDR = False # Run full detailed routing
    dr_params.minAccessPoints = 1 # Minimum number of pin access points
    dr_params.saveGuideUpdates = False # Do not save guide updates

    # Pass the parameters structure to the detailed router
    drter.setParams(dr_params)
    print(f"Detailed routing parameters set. Layer range: {global_route_min_layer} to {global_route_max_layer}.")

    # Run detailed routing
    drter.main()
    print("Detailed routing completed.")

    # Dump DEF after detailed routing
    write_def(design, "detailed_routed.def")

except Exception as e:
    print(f"Error during detailed routing: {e}")
    traceback.print_exc()


# --- Final Save ---
print("\n--- Saving Final Design ---")
# Write final OpenDB file containing all placement and routing information
final_odb_file = "final.odb"
try:
    design.writeDb(final_odb_file)
    print(f"Final design saved to {final_odb_file}")
except Exception as e:
    print(f"Error saving final ODB file {final_odb_file}: {e}")
    traceback.print_exc()

print("\n--- Script Finished ---")
