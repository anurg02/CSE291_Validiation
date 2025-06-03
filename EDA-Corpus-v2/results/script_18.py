import odb
import ppl
import mpl
import gpl
import opendp

# Assume design and libraries are already loaded.

# Create a clock signal on the clk_i port with a period of 20 ns
# The clock period is specified in nanoseconds (20 ns = 20000 ps)
design.evalTclString("create_clock -period 20 [get_ports clk_i] -name core_clock")

# Get the floorplanner object
floorplan = design.getFloorplan()

# Get the current core area of the design block
# Assume the block and its initial core area are already defined (e.g., from loading DEF)
block = design.getBlock()
core_area_rect = block.getCoreArea()

# Define the margin between core and die area in DBU
margin_dbu = design.micronToDBU(10)

# Calculate the die area based on the core area and the margin
die_area_rect = odb.Rect(core_area_rect.xMin() - margin_dbu,
                         core_area_rect.yMin() - margin_dbu,
                         core_area_rect.xMax() + margin_dbu,
                         core_area_rect.yMax() + margin_dbu)

# Find a site definition (replace with the actual site name from your technology LEF)
# Using a placeholder site name
site = floorplan.findSite("FreePDK45_38x28_10R_NP_162NW_34O")
if site is None:
    print("Error: Site not found. Please check your LEF files and site name.")
    # Exit or handle error appropriately
else:
    # Initialize the floorplan with the calculated die and core areas and the site
    floorplan.initFloorplan(die_area_rect, core_area_rect, site)

    # Create routing tracks based on the technology file
    floorplan.makeTracks()

# Configure and run I/O pin placement
io_placer_params = design.getIOPlacer().getParameters()
# Set minimum distance between I/O pins (optional, 0um requested)
io_placer_params.setMinDistance(design.micronToDBU(0))
# Get technology database and find relevant layers
tech = design.getTech().getDB().getTech()
metal8_layer = tech.findLayer("metal8")
metal9_layer = tech.findLayer("metal9")

# Check if layers exist
if metal8_layer is None or metal9_layer is None:
     print("Error: Metal layers for IO placement not found (metal8 or metal9).")
else:
    # Add horizontal placement layer (metal8)
    design.getIOPlacer().addHorLayer(metal8_layer)
    # Add vertical placement layer (metal9)
    design.getIOPlacer().addVerLayer(metal9_layer)
    # Run the I/O placer (using annealing mode as in example)
    design.getIOPlacer().runAnnealing(True) # True for random mode


# Find macro instances
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

# Configure and run macro placement if macros exist
if len(macros) > 0:
    macro_placer = design.getMacroPlacer()
    
    # Define the fence area for macros (confine them within the core)
    fence_lx = design.dbuToMicrons(core_area_rect.xMin())
    fence_ly = design.dbuToMicrons(core_area_rect.yMin())
    fence_ux = design.dbuToMicrons(core_area_rect.xMax())
    fence_uy = design.dbuToMicrons(core_area_rect.yMax())

    # Set macro placement parameters
    macro_placer.place(
        # Parameters for the placement algorithm
        num_threads = 64,
        max_num_macro = len(macros), # Place all macros found
        min_num_macro = 0,
        max_num_inst = 0,
        min_num_inst = 0,
        tolerance = 0.1,
        max_num_level = 2,
        coarsening_ratio = 10.0,
        large_net_threshold = 50,
        signature_net_threshold = 50,
        # Set halo region around each macro (5 um requested)
        halo_width = 5.0,
        halo_height = 5.0,
        # Set the fence to keep macros within the core area
        fence_lx = fence_lx,
        fence_ly = fence_ly,
        fence_ux = fence_ux,
        fence_uy = fence_uy,
        # Weights for objective functions (tune for results, examples from sample)
        area_weight = 0.1,
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        pin_access_th = 0.0,
        # Target utilization is mainly for standard cells, set below in global placement
        target_util = 0.25, # This might affect macro-aware density in global placement
        target_dead_space = 0.05,
        min_ar = 0.33,
        snap_layer = 4, # Example layer, adjust if needed
        bus_planning_flag = False,
        report_directory = ""
    )
else:
    print("No macros found in the design.")

# Configure and run global placement for standard cells
global_placer = design.getReplace()
# Set target utilization for standard cells (35% requested)
global_placer.setTargetUtil(0.35)
# Disable timing-driven mode (assuming functional flow)
global_placer.setTimingDrivenMode(False)
# Enable routability-driven mode to reduce congestion
global_placer.setRoutabilityDrivenMode(True)
# Set uniform target density mode
global_placer.setUniformTargetDensityMode(True)
# Limit initial placement iterations (example value, 10 from a different context in prompt)
# Note: Global placer iterations are different from a hypothetical global router iterations.
# The prompt asked for 10 iterations for the global router, but there is no such direct parameter.
# Setting initial placement iterations to a reasonable value here.
global_placer.setInitialPlaceMaxIter(10)
# Set initial density penalty factor
global_placer.setInitDensityPenalityFactor(0.05)

# Perform initial global placement
global_placer.doInitialPlace(threads = 4)
# Perform Nesterov-based global placement
global_placer.doNesterovPlace(threads = 4)
# Reset global placer state
global_placer.reset()

# Configure and run detailed placement
detailed_placer = design.getOpendp()

# Set maximum displacement for detailed placement (0 um in X and Y requested)
max_disp_x_dbu = design.micronToDBU(0)
max_disp_y_dbu = design.micronToDBU(0)

# Perform detailed placement
# Pass max_disp_x_dbu and max_disp_y_dbu directly as integers (DBU units)
# Note: Code Piece 1 suggests dividing by site width/height, but the API takes raw DBU displacement.
# Let's use the raw DBU displacement as per API interpretation, assuming the user wants 0 movement.
detailed_placer.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

# Note: The prompt asked for Global Routing iterations, but routing is not performed before the requested DEF dump.
# Global routing step is skipped as per the requirement to dump DEF after placement.

# Write the DEF file containing placement information
design.writeDef("placement.def")