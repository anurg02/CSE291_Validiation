import openroad as ord
from openroad import Tech, Design
import os, odb, drt, pdn, re
from pathlib import Path

# Set file path placeholders
libDir = Path("../../../Design/nangate45/lib")
lefDir = Path("../../../Design/nangate45/lef")
techlefDir = Path("../../../Design/nangate45/lef")
designDir = Path("../../../Design")

# Set design file name and top module name placeholders
design_name = "1_synth"
design_top_module_name = "gcd"

# Initialize Tech object
tech = Tech()

# Find and read library files (.lib)
libFiles = libDir.glob("*.lib")
for libFile in libFiles:
  tech.readLiberty(libFile.as_posix())

# Find and read LEF files (.lef, .tech.lef)
techLefFiles = lefDir.glob("*.tech.lef")
lefFiles = lefDir.glob('*.lef')
for techLefFile in techLefFiles:
  tech.readLef(techLefFile.as_posix())
for lefFile in lefFiles:
  tech.readLef(lefFile.as_posix())

# Initialize Design object
design = Design(tech)

# Read Verilog design file
verilogFile = designDir / str(design_name + ".v")
design.readVerilog(verilogFile.as_posix())

# Link the design
design.link(design_top_module_name)

# Set the clock period for the clock port "clk"
design.evalTclString("create_clock -period 20 [get_ports clk] -name core_clock")
# Set the clock to be propagated
design.evalTclString("set_propagated_clock [all_clocks]")

# Floorplanning
floorplan = design.getFloorplan()

# Set the floorplan utilization percentage
floorplan_utilization = 45
# Set the aspect ratio of the core area (height/width), default to 1.0 if not specified
floorplan_aspect_ratio = 1.0
# Set the spacing between the core and die area in microns
core_to_die_spacing_micron = 12
# Convert spacing to DBU (database units)
floorplan_core_spacing_dbu = [design.micronToDBU(core_to_die_spacing_micron) for _ in range(4)]

# Find a site definition in the LEF files (replace "site_name" with actual site name)
# This site is used to align standard cells and determine row height
site = floorplan.findSite("site_name")

# Initialize the floorplan with utilization, aspect ratio, core spacing, and site
floorplan.initFloorplan(floorplan_utilization, floorplan_aspect_ratio,
                        floorplan_core_spacing_dbu[0], floorplan_core_spacing_dbu[1],
                        floorplan_core_spacing_dbu[2], floorplan_core_spacing_dbu[3], site)

# Create standard cell rows based on the floorplan and site
floorplan.makeTracks()

# Place Pins using IOPlacer
io_placer_params = design.getIOPlacer().getParameters()
# Set random seed for reproducibility
io_placer_params.setRandSeed(42)
# Disable minimum distance in tracks
io_placer_params.setMinDistanceInTracks(False)
# Set minimum distance between pins to 0 DBU
io_placer_params.setMinDistance(design.micronToDBU(0))
# Set corner avoidance distance to 0 DBU
io_placer_params.setCornerAvoidance(design.micronToDBU(0))

# Add horizontal placement layer (M8)
io_placer_params.addHorLayer(design.getTech().getDB().getTech().findLayer("M8"))
# Add vertical placement layer (M9)
io_placer_params.addVerLayer(design.getTech().getDB().getTech().findLayer("M9"))

# Run IOPlacer in random mode (True for random, False for non-random)
io_placer_random_mode = True
design.getIOPlacer().run(io_placer_random_mode)

# Global Placement using RePlAce
global_placer = design.getReplace()
# Disable timing-driven placement for now
global_placer.setTimingDrivenMode(False)
# Enable routability-driven placement
global_placer.setRoutabilityDrivenMode(True)
# Enable uniform target density
global_placer.setUniformTargetDensityMode(True)
# Set the maximum iterations for initial placement
global_placer.setInitialPlaceMaxIter(10)
# Set the density penalty factor for initial placement
global_placer.setInitDensityPenalityFactor(0.05)

# Perform initial global placement
global_placer.doInitialPlace()
# Perform Nesterov-based global placement
global_placer.doNesterovPlace()
# Reset the global placer internal state
global_placer.reset()

# Macro Placement
# Get all instances and filter for those that are block masters (macros)
macros = [inst for inst in ord.get_db_block().getInsts() if inst.getMaster().isBlock()]

# Check if there are any macros in the design
if len(macros) > 0:
  macro_placer = design.getMacroPlacer()
  # Set the halo size around macros in microns (space kept clear of standard cells)
  macro_halo_x_micron, macro_halo_y_micron = 5, 5
  macro_placer.setHalo(macro_halo_x_micron, macro_halo_y_micron)

  # Set the minimum channel width between macros in microns
  macro_channel_x_micron, macro_channel_y_micron = 5, 5
  macro_placer.setChannel(macro_channel_x_micron, macro_channel_y_micron)

  # Set the fence region for placing macros in microns (bottom-left x, top-right x, bottom-left y, top-right y)
  fence_lx_micron, fence_ux_micron = 32, 55
  fence_ly_micron, fence_uy_micron = 32, 60
  design.getMacroPlacer().setFenceRegion(fence_lx_micron, fence_ux_micron, fence_ly_micron, fence_uy_micron)

  # Set the layer to which macros should be snapped (usually a metal layer like M4)
  snap_layer = design.getTech().getDB().getTech().findLayer("M4")
  macro_placer.setSnapLayer(snap_layer)

  # Run macro placement (using a common strategy like minimizing wirelength)
  macro_placer.placeMacrosCornerMaxWl() # or placeMacrosCornerMinWL() or placeMacrosPinWL()

# Detailed Placement using OpenDP
detailed_placer = design.getOpendp()

# Get the site dimensions from the first row
site = design.getBlock().getRows()[0].getSite()

# Set the maximum allowed displacement for detailed placement in microns
max_disp_x_micron = 0.5
max_disp_y_micron = 0.5

# Convert maximum displacement from microns to site units
max_disp_x_site_units = int(design.micronToDBU(max_disp_x_micron) / site.getWidth())
max_disp_y_site_units = int(design.micronToDBU(max_disp_y_micron) / site.getHeight())

# Perform detailed placement
# Arguments: max_disp_x, max_disp_y, cell_row_placement_type, enable_multi_row_cells
detailed_placer.detailedPlacement(max_disp_x_site_units, max_disp_y_site_units, "", False)

# Write the DEF file after placement
design.writeDef("placement.def")

