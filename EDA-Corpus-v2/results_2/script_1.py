# OpenROAD Python script for Place and Floorplan flow

import odb
import pdn # Might be needed for PDN setup, but not used in this specific script
import drt # Might be needed for routing, but not used in this specific script
import openroad as ord
import ifp # Needed for IOPlacer
import gpl # Needed for Global Placer (Replace)
import mpl # Needed for Macro Placer
import opendp # Needed for Detailed Placer

# Get the OpenROAD design object
# Assumes a design (synthesized netlist) and libraries are already loaded
design = ord.get_design()
block = design.getBlock()
tech = design.getTech().getDB().getTech()

print("Starting placement flow...")

# 1. Set the clock definition
clock_port_name = "clk"
clock_period_ns = 20.0
clock_name = "core_clock"

print(f"Setting up clock '{clock_name}' on port '{clock_port_name}' with period {clock_period_ns} ns...")
clock_port = block.findBTerm(clock_port_name)
if clock_port:
    # Use native Python API for creating clock
    # Note: ord.create_clock takes period in nanoseconds
    ord.create_clock(clock_name, clock_period_ns, [clock_port])
    print(f"Clock '{clock_name}' created successfully.")
else:
    print(f"Warning: Clock port '{clock_port_name}' not found. Cannot set clock.")

# 2. Perform floorplanning
print("Performing floorplanning...")

floorplan = design.getFloorplan()

# Find a core site in the library
site = None
for lib in design.getDb().getLibs():
    for s in lib.getSites():
        if s.getClass() == "CORE":
            site = s
            print(f"Using core site: {site.getName()}")
            break
    if site:
        break

if site is None:
    print("Error: Could not find a core site in the library.")
    # Exit or handle error appropriately if site is mandatory for floorplan
else:
    # Floorplan parameters
    target_utilization = 0.45
    # Aspect ratio is not specified, using 1.0 as default (square core)
    aspect_ratio = 1.0
    core_to_die_margin_microns = 12.0
    core_to_die_margin_dbu = design.micronToDBU(core_to_die_margin_microns)

    # Initialize floorplan with utilization, aspect ratio, margins, and site
    # initFloorplan calculates core area based on target utilization of instances,
    # then calculates die area by adding margins to the core area.
    # Margins are applied to all four sides (left, bottom, right, top).
    floorplan.initFloorplan(target_utilization, aspect_ratio,
                            core_to_die_margin_dbu, core_to_die_margin_dbu,
                            core_to_die_margin_dbu, core_to_die_margin_dbu,
                            site)

    # Create placement tracks based on the site definition
    floorplan.makeTracks()
    print(f"Floorplan created with target utilization {target_utilization} and {core_to_die_margin_microns} um core-to-die margin.")

# 3. Place the pins (IO Placement)
print("Placing IO pins...")

io_placer = design.getIOPlacer()
io_params = io_placer.getParameters()

# Set parameters as requested or for better results
io_params.setRandSeed(42) # for reproducibility
io_params.setMinDistanceInTracks(False) # Minimum distance is absolute, not grid-based
io_params.setMinDistance(design.micronToDBU(0)) # Set minimum distance between pins (0 means no specific minimum enforced beyond track grid)
io_params.setCornerAvoidance(design.micronToDBU(0)) # Do not avoid corners

# Find specified metal layers for pin placement
pin_layer_h_name = "metal8"
pin_layer_v_name = "metal9"

metal8 = tech.findLayer(pin_layer_h_name)
metal9 = tech.findLayer(pin_layer_v_name)

if metal8:
    # Add Metal 8 as a horizontal routing layer for pins on sides where horizontal tracks exist
    io_placer.addHorLayer(metal8)
    print(f"Using layer '{pin_layer_h_name}' for horizontal pin placement.")
else:
    print(f"Warning: Layer '{pin_layer_h_name}' not found. Cannot use it for pin placement.")

if metal9:
    # Add Metal 9 as a vertical routing layer for pins on sides where vertical tracks exist
    io_placer.addVerLayer(metal9)
    print(f"Using layer '{pin_layer_v_name}' for vertical pin placement.")
else:
    print(f"Warning: Layer '{pin_layer_v_name}' not found. Cannot use it for pin placement.")

# Run the IO placement algorithm
# True for random mode (faster initial results), False for annealing (potentially better, slower)
IOPlacer_random_mode = True
io_placer.runAnnealing(IOPlacer_random_mode)

print("IO pins placed.")

# 4. Place the macros
print("Placing macros...")

# Identify instances that are macros (have a block master)
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    print(f"Found {len(macros)} macros.")
    macro_placer = design.getMacroPlacer()

    # Define the fence region for macros in microns
    fence_lx_microns = 32.0
    fence_ly_microns = 32.0
    fence_ux_microns = 55.0
    fence_uy_microns = 60.0

    # Set the fence region (macros will be placed inside this bounding box)
    # Coordinates are in microns
    macro_placer.setFenceRegion(fence_lx_microns, fence_ly_microns, fence_ux_microns, fence_uy_microns)
    print(f"Macro fence region set to [{fence_lx_microns},{fence_ly_microns}] to [{fence_ux_microns},{fence_uy_microns}] um.")

    # Set the halo (buffer zone) around each macro in microns
    # This helps maintain spacing around macros
    halo_microns = 5.0
    macro_placer.setHalo(halo_microns, halo_microns) # width, height
    print(f"Macro halo set to {halo_microns} um.")

    # Run the macro placement algorithm
    # Using a minimal set of parameters, adjust if specific tuning is needed
    macro_placer.place(
        num_threads=4, # Number of threads to use
        max_num_macro=len(macros), # Place all found macros
        fence_weight=10.0, # Give weight to the fence constraint
        boundary_weight=50.0, # Give weight to stay within the core/die boundary
        halo_weight=1.0 # Give weight to the halo constraint
        # Other parameters can be added for further tuning if needed
    )
    print("Macros placed.")
else:
    print("No macros found in the design. Skipping macro placement.")


# 5. Place the standard cells (Global and Detailed Placement)
print("Placing standard cells...")

# Global Placement (using the 'replace' tool)
global_placer = design.getReplace()

# Disable timing-driven placement (as timing was not specified as a goal)
global_placer.setTimingDrivenMode(False)
# Enable routability-driven placement for better routing results later
global_placer.setRoutabilityDrivenMode(True)
# Use uniform target density across the core area
global_placer.setUniformTargetDensityMode(True)

# Set initial placement iterations.
# The prompt mentions "iteration of the global router as 10 times",
# but this is a placement stage. Interpreting this as initial placement iterations.
initial_placement_iterations = 10
global_placer.setInitialPlaceMaxIter(initial_placement_iterations)
print(f"Global placement initial iterations set to {initial_placement_iterations}.")

# Run initial placement
print("Running initial placement...")
global_placer.doInitialPlace(threads=4) # Use 4 threads (adjust as needed)
print("Initial placement completed.")

# Run Nesterov-accelerated placement
print("Running Nesterov-accelerated placement...")
global_placer.doNesterovPlace(threads=4) # Use 4 threads (adjust as needed)
print("Nesterov placement completed.")

# Reset the global placer after completion
global_placer.reset()


# Detailed Placement (using the 'opendp' tool)
print("Running detailed placement...")
detailed_placer = design.getOpendp()

# Define the maximum displacement allowed in microns
max_disp_x_microns = 0.5
max_disp_y_microns = 0.5
# Convert maximum displacement from microns to DBU
max_disp_x_dbu = int(design.micronToDBU(max_disp_x_microns))
max_disp_y_dbu = int(design.micronToDBU(max_disp_y_microns))

# Remove any previously inserted filler cells before placement (harmless if none exist)
detailed_placer.removeFillers()

# Perform detailed placement
# Arguments: max_disp_x, max_disp_y, placement_row_name (empty string means all rows), check_placement
detailed_placer.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print(f"Detailed placement completed with max displacement {max_disp_x_microns} um in X and {max_disp_y_microns} um in Y.")


# 6. Save the design in DEF format after placement
output_def_file = "placement.def"
print(f"Saving placement results to {output_def_file}...")
design.writeDef(output_def_file)
print("Placement flow completed.")

# Note: The request mentioned setting global router iterations but did not ask to run routing.
# The script performs placement and saves the DEF file as requested.
# PDN and CTS steps were not requested in this specific prompt.