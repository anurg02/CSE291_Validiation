import openroad as ord
import odb
import ifp
import ppl
import mpl
import gpl
import opendp
import grt

# Assume libraries, LEF, and Verilog are already loaded and linked
# e.g.,
# ord.read_liberty("sky130_fd_sc_hd__fast.lib")
# ord.read_lef("sky130_tech.lef")
# ord.read_lef("sky130_fd_sc_hd.lef")
# ord.read_verilog("top.v")
# ord.link_design("top")
# ord.read_sdc("top.sdc") # Assuming sdc is needed for clock

# Set the clock period
# Create a clock named "clk" on the port "clk" with a period of 20 ns
ord.evalTclString("create_clock -period 20 [get_ports clk]")

# --- Floorplanning ---
# Set target utilization for floorplanning
ord.evalTclString("set_utilization 0.45")
# Set spacing between core and die boundary (12 microns)
ord.evalTclString("set_placement_boundaries -core_to_die 12")
# Initialize the floorplan based on the settings (utilization, core_to_die)
ord.evalTclString("init_floorplan")

# --- I/O Pin Placement ---
# Get the IO Placer object
io_placer = design.getIOPlacer()
# Get IO Placer parameters (though not explicitly needed for layers/run)
# params = io_placer.getParameters()

# Get technology database and find the layers for pin placement
tech = design.getTech().getDB().getTech()
metal8_layer = tech.findLayer("metal8")
metal9_layer = tech.findLayer("metal9")

# Add horizontal and vertical layers for pin placement
if metal8_layer:
    io_placer.addHorLayer(metal8_layer)
else:
    print("Warning: metal8 layer not found for IO placement.")
if metal9_layer:
    io_placer.addVerLayer(metal9_layer)
else:
     print("Warning: metal9 layer not found for IO placement.")

# Run IO pin placement using annealing algorithm
# IOPlacer_random_mode = True # Example uses a bool, let's stick to that
# io_placer.runAnnealing(IOPlacer_random_mode) # API description doesn't show random_mode bool
io_placer.runAnnealing() # Run annealing without random mode flag based on API description

# --- Macro Placement ---
# Get list of macro instances in the design
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

# Get the Macro Placer object
macro_placer = design.getMacroPlacer()

# Set the fence region for macros (bottom-left (32, 32) um, top-right (55, 60) um)
# API 11 suggests setting the fence region before calling place
fence_lx_um = 32.0
fence_ly_um = 32.0
fence_ux_um = 55.0
fence_uy_um = 60.0
macro_placer.setFenceRegion(fence_lx_um, fence_ly_um, fence_ux_um, fence_uy_um)

# Set halo region around macros (5 microns)
halo_width_um = 5.0
halo_height_um = 5.0

# Note: The Python API documentation/examples for MacroPlacer.place do not show a direct parameter
# for minimum distance *between* macros. The request for 5um minimum distance is not
# directly supported by the available API examples for `mpl.place`.
# We proceed with fence and halo settings.

# Run macro placement
# Using the 'place' function from Example 1 which supports fence and halo
# Many parameters are omitted from the prompt; using default or reasonable values if needed by the API.
# The API description for `mpl.place` parameters is not directly available in the knowledge base,
# but Example 1 provides a detailed list of parameters.
# We will use the parameters from Example 1, focusing on fence, halo, and macro count if available.
if len(macros) > 0:
    macro_placer.place(
        num_threads = 64, # Example value
        max_num_macro = len(macros), # Place all macros found
        min_num_macro = 0,
        max_num_inst = 0,
        min_num_inst = 0,
        tolerance = 0.1, # Example value
        max_num_level = 2, # Example value
        coarsening_ratio = 10.0, # Example value
        large_net_threshold = 50, # Example value
        signature_net_threshold = 50, # Example value
        halo_width = halo_width_um, # Set halo width in microns
        halo_height = halo_height_um, # Set halo height in microns
        # Fence region is set via setFenceRegion(), not directly in place() args based on API 11.
        # The fence parameters in Example 1 seem redundant if setFenceRegion is used.
        # Leaving them out as setFenceRegion should be the correct method per API 11.
        # fence_lx = design.micronToDBU(fence_lx_um), # Corrected unit based on Example 1
        # fence_ly = design.micronToDBU(fence_ly_um), # Corrected unit based on Example 1
        # fence_ux = design.micronToDBU(fence_ux_um), # Corrected unit based on Example 1
        # fence_uy = design.micronToDBU(fence_uy_um), # Corrected unit based on Example 1
        area_weight = 0.1, # Example value
        outline_weight = 100.0, # Example value
        wirelength_weight = 100.0, # Example value
        guidance_weight = 10.0, # Example value
        fence_weight = 10.0, # Example value
        boundary_weight = 50.0, # Example value
        notch_weight = 10.0, # Example value
        macro_blockage_weight = 10.0, # Example value
        pin_access_th = 0.0, # Example value
        target_util = 0.25, # Example value (different from chip util, maybe internal?)
        target_dead_space = 0.05, # Example value
        min_ar = 0.33, # Example value
        snap_layer = 4, # Example value
        bus_planning_flag = False, # Example value
        report_directory = "" # Example value
    )

# --- Global Placement ---
# Get the Global Placer object
global_placer = design.getReplace()
# Configure global placement (using settings from Example 1 as defaults)
global_placer.setTimingDrivenMode(False) # Assuming non-timing driven unless specified
global_placer.setRoutabilityDrivenMode(True) # Assuming routability driven
global_placer.setUniformTargetDensityMode(True)
global_placer.setInitialPlaceMaxIter(10) # Example value
global_placer.setInitDensityPenalityFactor(0.05) # Example value

# Run initial global placement
# global_placer.doInitialPlace(threads = 4) # Example value
# global_placer.doNesterovPlace(threads = 4) # Example value
# Running the main placement flow
global_placer.globalPlacement() # A common high-level call

# Reset the placer after use
global_placer.reset()

# --- Detailed Placement ---
# Get the Detailed Placer object
detailed_placer = design.getOpendp()

# Set maximum displacement for detailed placement (0.5 um in x and y)
max_disp_x_um = 0.5
max_disp_y_um = 0.5

# Convert microns to DBU
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

# In detailedPlacement, the displacement values are often relative to site size,
# or in DBU directly depending on the API version/wrapper.
# Code Piece 1 uses DBU directly. Let's follow that.
# design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

# Newer API versions might take site units or different parameters.
# Let's check the site dimensions if needed, but try DBU first as per example.
# If detailedPlacement fails with DBU, it might expect displacement in site units.
# Site = design.getBlock().getRows()[0].getSite()
# max_disp_x_site = int(max_disp_x_dbu / site.getWidth())
# max_disp_y_site = int(max_disp_y_dbu / site.getHeight())
# detailed_placer.detailedPlacement(max_disp_x_site, max_disp_y_site, "", False)

# Remove filler cells if any exist before detailed placement (as shown in Code Piece 1)
detailed_placer.removeFillers()

# Run detailed placement
# Using the direct DBU approach from Code Piece 1
detailed_placer.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)


# --- Dump DEF file after placement ---
# Save the design database in DEF format
design.writeDef("placement.def")


# --- Global Routing ---
# Set iteration count for global router using Tcl variable
# Assuming the Tcl variable 'global_router::max_iterations' controls this.
ord.evalTclString("set global_router::max_iterations 10")

# Get the Global Router object
global_router = design.getGlobalRouter()

# Run global routing
# The 'True' argument typically enables congestion analysis and fixing
global_router.globalRoute(True)

# Detailed routing would typically follow global routing, but was not requested.
# Example:
# drt = design.getTritonRoute()
# drt_params = drt.getParams()
# drt.setParams(drt_params)
# drt.detailedRoute()

# Final saves could be added here if needed, e.g.,
# design.writeDb("final.odb")
# ord.evalTclString("write_verilog final_routed.v")