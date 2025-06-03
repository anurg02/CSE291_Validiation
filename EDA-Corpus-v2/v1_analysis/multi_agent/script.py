import openroad as ord
from openroad import Tech, Design
import os, odb, drt, pdn, re
from pathlib import Path

# --- User Configuration ---
# Replace these with your actual file paths and design details
libDir = Path("../../../Design/nangate45/lib")          # Directory containing liberty files (*.lib)
lefDir = Path("../../../Design/nangate45/lef")          # Directory containing LEF files (*.lef, *.tech.lef)
designDir = Path("../../../Design")    # Directory containing your Verilog netlist (*.v)
outputDir = Path("output")                 # Output directory for DEF files and reports

design_name = "1_synth"       # Base name of your Verilog file (e.g., "my_design" for "my_design.v")
design_top_module_name = "gcd" # Name of the top module in your Verilog
clock_port_name = "clk"                    # Name of the clock port in the Verilog
site_name = "FreePDK45_38x28_10R_NP_162NW_34O"                         # Name of the standard cell site from your LEF (e.g., "CORE")

# --- Physical Design Parameters ---
floorplan_utilization = 45               # Target utilization percentage
floorplan_core_spacing_um = 12           # Spacing between core and die boundary in microns

macro_channel_um = 5                     # Minimum spacing between macros in microns
macro_halo_um = 5                        # Halo (exclusion zone for std cells) around macros in microns
fence_llx_um, fence_lly_um = 32, 32      # Macro fence region bottom-left corner in microns
fence_urx_um, fence_ury_um = 55, 60      # Macro fence region top-right corner in microns

detailed_placement_max_disp_um = 0.5     # Max displacement for detailed placement in microns

cts_buffer_cell = "BUF_X2"               # Standard cell name to use as clock buffer
clock_wire_resistance = 0.03574          # Unit resistance for clock wires
clock_wire_capacitance = 0.07516         # Unit capacitance for clock wires
signal_wire_resistance = 0.03574         # Unit resistance for signal wires
signal_wire_capacitance = 0.07516        # Unit capacitance for signal wires

pdn_core_ring_m7_m8_width_um = 5
pdn_core_ring_m7_m8_spacing_um = 5
pdn_stdcell_grid_m1_width_um = 0.07
pdn_macro_grid_m4_width_um = 1.2
pdn_macro_grid_m4_spacing_um = 1.2
pdn_macro_grid_m4_pitch_um = 6
pdn_core_strap_m7_width_um = 1.4
pdn_core_strap_m7_spacing_um = 1.4
pdn_core_strap_m7_pitch_um = 10.8
pdn_macro_grid_m5_m6_width_um = 1.2      # Grid width for macros on M5 and M6
pdn_macro_grid_m5_m6_spacing_um = 1.2    # Grid spacing for macros on M5 and M6
pdn_macro_grid_m5_m6_pitch_um = 6        # Grid pitch for macros on M5 and M6
pdn_parallel_via_cut_pitch_um = 0        # Via cut pitch between parallel grids
pdn_overall_offset_um = 0                # General offset for grids/rings

global_router_adjustment = 0.5           # Congestion adjustment for global router
# Note: Setting global router iterations directly via Python API is not standard.
# OpenROAD's TritonRoute typically uses internal heuristics or config files.
# The prompt mentions 30 iterations, which might refer to a specific internal loop
# or potentially confusion with global placement iterations.
# We will proceed with the standard global routing call.

detailed_router_end_iter = 1             # Number of detailed routing iterations
detailed_router_bottom_layer = "M1"      # Bottom layer for detailed routing
detailed_router_top_layer = "M7"         # Top layer for detailed routing

# --- Setup ---
outputDir.mkdir(parents=True, exist_ok=True) # Create output directory if it doesn't exist

# Initialize technology and design objects
tech = Tech()

# Read liberty, technology LEF, and cell LEF files
libFiles = libDir.glob("*.lib")
techLefFiles = lefDir.glob("*.tech.lef")
lefFiles = lefDir.glob('*.lef')

print("Reading liberty files...")
for libFile in libFiles:
  print(f"  Reading {libFile.name}")
  tech.readLiberty(libFile.as_posix())

print("Reading technology LEF files...")
for techLefFile in techLefFiles:
  print(f"  Reading {techLefFile.name}")
  tech.readLef(techLefFile.as_posix())

print("Reading cell LEF files...")
for lefFile in lefFiles:
  print(f"  Reading {lefFile.name}")
  tech.readLef(lefFile.as_posix())

# Create design instance with loaded tech
design = Design(tech)

# Read Verilog netlist and link top module
verilogFile = designDir / (design_name + ".v")
print(f"Reading Verilog file: {verilogFile.name}")
design.readVerilog(verilogFile.as_posix())

print(f"Linking design: {design_top_module_name}")
design.link(design_top_module_name)

# --- Set Clocks ---
print("Setting clock...")
# Create a clock with the specified period on the clock port
design.evalTclString(f"create_clock -period 40 [get_ports {clock_port_name}] -name core_clock")
# Set the clock to be propagated for timing analysis
design.evalTclString("set_propagated_clock [all_clocks]")

# --- Floorplanning ---
print("Performing floorplanning...")
floorplan = design.getFloorplan()

# Convert micron spacing to DBU
floorplan_core_spacing_dbu = [design.micronToDBU(floorplan_core_spacing_um) for _ in range(4)]
floorplan_aspect_ratio = 1.0 # Default aspect ratio

# Find the standard cell site definition in the LEF
site = floorplan.findSite(site_name)
if site is None:
  print(f"Error: Site '{site_name}' not found in LEF files. Please check site_name in user config.")
  exit(1)

# Initialize the floorplan
# Parameters: utilization, aspect_ratio, core_offset_x, core_offset_y, core_offset_width, core_offset_height, site
floorplan.initFloorplan(floorplan_utilization, floorplan_aspect_ratio,
                        floorplan_core_spacing_dbu[0], floorplan_core_spacing_dbu[1],
                        floorplan_core_spacing_dbu[2], floorplan_core_spacing_dbu[3], site)

# Make placement tracks based on the floorplan
floorplan.makeTracks()

# Dump DEF after floorplanning
design.writeDef(outputDir / "floorplan.def")
print(f"Dumped DEF: {outputDir / 'floorplan.def'}")

# --- Place Pins ---
print("Placing pins...")
io_placer = design.getIOPlacer()
params = io_placer.getParameters()
params.setRandSeed(42)
params.setMinDistanceInTracks(False)
params.setMinDistance(design.micronToDBU(0))
params.setCornerAvoidance(design.micronToDBU(0))

# Find the desired routing layers for pin placement
m8_layer = design.getTech().getDB().getTech().findLayer("M8")
m9_layer = design.getTech().getDB().getTech().findLayer("M9")

# Add horizontal and vertical layers for pin placement
if m8_layer:
  io_placer.addHorLayer(m8_layer)
else:
  print("Warning: M8 layer not found for pin placement.")
if m9_layer:
  io_placer.addVerLayer(m9_layer)
else:
  print("Warning: M9 layer not found for pin placement.")

# Run I/O placement in random mode (True/False)
io_placer.run(True)

# Dump DEF after pin placement
design.writeDef(outputDir / "pin_placement.def")
print(f"Dumped DEF: {outputDir / 'pin_placement.def'}")

# --- Global Placement ---
print("Performing global placement...")
gpl = design.getReplace()
gpl.setTimingDrivenMode(False)     # Disable timing-driven global placement
gpl.setRoutabilityDrivenMode(True) # Enable routability-driven placement
gpl.setUniformTargetDensityMode(True)

# Set the maximum iterations for initial placement (often related to global placement convergence)
# The prompt mentions 30 iterations for the global router, but this is the setting for RePlace.
gpl.setInitialPlaceMaxIter(30)
gpl.setInitDensityPenalityFactor(0.05)

gpl.doInitialPlace()
gpl.doNesterovPlace()
gpl.reset()

# Dump DEF after global placement
design.writeDef(outputDir / "global_placement.def")
print(f"Dumped DEF: {outputDir / 'global_placement.def'}")

# --- Macro Placement ---
print("Performing macro placement...")
# Find all instances that are macros (masters are blocks)
macros = [inst for inst in ord.get_db_block().getInsts() if inst.getMaster().isBlock()]

# Check if there are any macros in the design
if len(macros) > 0:
  mpl = design.getMacroPlacer()

  # Convert micron values to DBU for macro placer settings
  macro_channel_dbu = design.micronToDBU(macro_channel_um)
  macro_halo_dbu = design.micronToDBU(macro_halo_um)
  fence_llx_dbu = design.micronToDBU(fence_llx_um)
  fence_lly_dbu = design.micronToDBU(fence_lly_um)
  fence_urx_dbu = design.micronToDBU(fence_urx_um)
  fence_ury_dbu = design.micronToDBU(fence_ury_um)

  # Set the halo around macros in DBU (exclusion zone for standard cells)
  mpl.setHalo(macro_halo_dbu, macro_halo_dbu)

  # Set the minimum channel width between macros in DBU
  mpl.setChannel(macro_channel_dbu, macro_channel_dbu)

  # Set the fence region in DBU (macros will be placed within this area)
  mpl.setFenceRegion(fence_llx_dbu, fence_urx_dbu, fence_lly_dbu, fence_ury_dbu)

  # Find the layer to which macros should snap (usually M4 or a macro grid layer)
  snap_layer = design.getTech().getDB().getTech().findLayer("M4") # Assuming M4 for snapping
  if snap_layer:
    mpl.setSnapLayer(snap_layer)
  else:
    print("Warning: M4 layer not found for macro snap layer. Macros may not snap correctly.")

  # Place the macros (using a specific strategy, e.g., maximizing bounding box wirelength)
  mpl.placeMacrosCornerMaxWl()
  # mpl.placeMacrosCornerMinWL() # Alternative strategy

else:
    print("No macros found in the design. Skipping macro placement.")

# Dump DEF after macro placement
design.writeDef(outputDir / "macro_placement.def")
print(f"Dumped DEF: {outputDir / 'macro_placement.def'}")

# --- Detailed Placement ---
print("Performing detailed placement...")
# Get the first row's site to determine site dimensions for displacement calculation
try:
    site = design.getBlock().getRows()[0].getSite()
except IndexError:
    print("Error: No placement rows found. Cannot determine site dimensions for detailed placement.")
    exit(1)

# Calculate maximum displacement in site units
max_disp_x_dbu = design.micronToDBU(detailed_placement_max_disp_um)
max_disp_y_dbu = design.micronToDBU(detailed_placement_max_disp_um)

# Ensure site width/height are not zero before division
site_width = site.getWidth()
site_height = site.getHeight()

if site_width == 0 or site_height == 0:
    print("Error: Site width or height is zero. Cannot calculate detailed placement displacement.")
    exit(1)

max_disp_x_site = int(max_disp_x_dbu / site_width)
max_disp_y_site = int(max_disp_y_dbu / site_height)

# Perform detailed placement
# Arguments: max_disp_x_sites, max_disp_y_sites, cell_pin_check_pattern, legalization_flag (True/False)
# Legalization is typically handled by filler placement, so False is common here.
design.getOpendp().detailedPlacement(max_disp_x_site, max_disp_y_site, "", False)

# Dump DEF after detailed placement
design.writeDef(outputDir / "detailed_placement.def")
print(f"Dumped DEF: {outputDir / 'detailed_placement.def'}")

# --- Clock Tree Synthesis (CTS) ---
print("Performing Clock Tree Synthesis...")
# Ensure clocks are propagated (needed before CTS)
design.evalTclString("set_propagated_clock [all_clocks]")

# Set wire RC values for clock and signal nets
design.evalTclString(f"set_wire_rc -clock -resistance {clock_wire_resistance} -capacitance {clock_wire_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {signal_wire_resistance} -capacitance {signal_wire_capacitance}")

# Get the TritonCTS object
cts = design.getTritonCts()
# Get CTS parameters
cts_parms = cts.getParms()

# Set wire segment unit length (in DBU)
# The prompt specified 20, assuming microns, converting to DBU.
cts_parms.setWireSegmentUnit(design.micronToDBU(20))

# Set the list of available buffer cells for CTS
cts.setBufferList(cts_buffer_cell)
# Set the specific buffer cell to use for the clock root and sinks
cts.setRootBuffer(cts_buffer_cell)
cts.setSinkBuffer(cts_buffer_cell)

# Run the CTS engine
cts.runTritonCts()

# Dump DEF after CTS
design.writeDef(outputDir / "cts.def")
print(f"Dumped DEF: {outputDir / 'cts.def'}")

# --- Detailed Placement (Post-CTS) ---
print("Performing detailed placement after CTS...")
# Rerun detailed placement after CTS to fix any legalization issues introduced by buffers
# Use the same displacement settings as before
design.getOpendp().detailedPlacement(max_disp_x_site, max_disp_y_site, "", False)

# Dump DEF after post-CTS detailed placement
design.writeDef(outputDir / "post_cts_detailed_placement.def")
print(f"Dumped DEF: {outputDir / 'post_cts_detailed_placement.def'}")

# --- Add Filler Cells ---
print("Adding filler cells...")
db = ord.get_db()
filler_masters = list()
# Define the prefix for filler cells (adjust if necessary for your library)
filler_cells_prefix = "filler_.*"

# Find all filler cell masters in the loaded libraries
for lib in db.getLibs():
  for master in lib.getMasters():
    master_name = master.getConstName()
    if re.fullmatch(filler_cells_prefix, master_name) is not None:
      filler_masters.append(master)

# Perform filler cell placement if filler masters are found
if len(filler_masters) == 0:
  print(f"Warning: No filler cells found with prefix '{filler_cells_prefix}'. Skipping filler placement.")
else:
  design.getOpendp().fillerPlacement(filler_masters, filler_cells_prefix)
  print("Filler cells placed.")

# Dump DEF after filler placement
design.writeDef(outputDir / "filler_placement.def")
print(f"Dumped DEF: {outputDir / 'filler_placement.def'}")

# --- Power Planning (PDN) ---
print("Performing Power Planning (PDN)...")

# Global Connect: Mark power and ground nets as special and connect them to standard cell pins
# Find the power and ground nets by name (assuming VDD and VSS)
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")

# Create nets if they don't exist (useful for initial setup)
if VDD_net is None:
  VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
  VDD_net.setSpecial()
  VDD_net.setSigType("POWER")
  print("Created VDD net.")
if VSS_net is None:
  VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
  VSS_net.setSpecial()
  VSS_net.setSigType("GROUND")
  print("Created VSS net.")

# Connect all pins matching the pattern to the VDD net
design.getBlock().addGlobalConnect(region = None, instPattern = ".*",
                                  pinPattern = "^VDD$", net = VDD_net,
                                  do_connect = True)
# Add other VDD-like pin patterns if necessary (adjust based on library)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*",
                                  pinPattern = "^VDDPE$", net = VDD_net,
                                  do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*",
                                  pinPattern = "^VDDCE$", net = VDD_net,
                                  do_connect = True)

# Connect all pins matching the pattern to the VSS net
design.getBlock().addGlobalConnect(region = None, instPattern = ".*",
                                  pinPattern = "^VSS$", net = VSS_net,
                                  do_connect = True)
# Add other VSS-like pin patterns if necessary (adjust based on library)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*",
                                  pinPattern = "^VSSE$", net = VSS_net,
                                  do_connect = True)
# Apply the global connections
design.getBlock().globalConnect()
print("Global power/ground connections added.")

# Voltage Domains
# Get the PDN generator object
pdngen = design.getPdnGen()
# Define the core voltage domain
pdngen.setCoreDomain(power = VDD_net, switched_power = None,
                    ground = VSS_net, secondary = [])

# Convert PDN parameters from microns to DBU
pdn_core_ring_m7_m8_width_dbu = design.micronToDBU(pdn_core_ring_m7_m8_width_um)
pdn_core_ring_m7_m8_spacing_dbu = design.micronToDBU(pdn_core_ring_m7_m8_spacing_um)
pdn_stdcell_grid_m1_width_dbu = design.micronToDBU(pdn_stdcell_grid_m1_width_um)
pdn_macro_grid_m4_width_dbu = design.micronToDBU(pdn_macro_grid_m4_width_um)
pdn_macro_grid_m4_spacing_dbu = design.micronToDBU(pdn_macro_grid_m4_spacing_um)
pdn_macro_grid_m4_pitch_dbu = design.micronToDBU(pdn_macro_grid_m4_pitch_um)
pdn_core_strap_m7_width_dbu = design.micronToDBU(pdn_core_strap_m7_width_um)
pdn_core_strap_m7_spacing_dbu = design.micronToDBU(pdn_core_strap_m7_spacing_um)
pdn_core_strap_m7_pitch_dbu = design.micronToDBU(pdn_core_strap_m7_pitch_um)
pdn_macro_grid_m5_m6_width_dbu = design.micronToDBU(pdn_macro_grid_m5_m6_width_um)
pdn_macro_grid_m5_m6_spacing_dbu = design.micronToDBU(pdn_macro_grid_m5_m6_spacing_um)
pdn_macro_grid_m5_m6_pitch_dbu = design.micronToDBU(pdn_macro_grid_m5_m6_pitch_um)
pdn_parallel_via_cut_pitch_dbu = design.micronToDBU(pdn_parallel_via_cut_pitch_um)
pdn_overall_offset_dbu = design.micronToDBU(pdn_overall_offset_um)

core_ring_core_offset_dbu = [design.micronToDBU(0) for _ in range(4)]
core_ring_pad_offset_dbu = [design.micronToDBU(0) for _ in range(4)]
pdn_cut_pitch_dbu = [pdn_parallel_via_cut_pitch_dbu, pdn_parallel_via_cut_pitch_dbu]

# Find routing layers
m1 = design.getTech().getDB().getTech().findLayer("M1")
m4 = design.getTech().getDB().getTech().findLayer("M4")
m5 = design.getTech().getDB().getTech().findLayer("M5")
m6 = design.getTech().getDB().getTech().findLayer("M6")
m7 = design.getTech().getDB().getTech().findLayer("M7")
m8 = design.getTech().getDB().getTech().findLayer("M8")

if not all([m1, m4, m7, m8]):
    print("Error: Required routing layers (M1, M4, M7, M8) for core PDN not found.")
    exit(1)

# Define power grid for the core (std cells and potentially macros covered by core grid)
core_domains = [pdngen.findDomain("Core")]
# No halo for the main core grid relative to core boundary
core_grid_halo_dbu = [design.micronToDBU(0) for _ in range(4)]

for domain in core_domains:
  # Create a core grid definition
  core_grid_name = "core_pdn_grid"
  pdngen.makeCoreGrid(domain = domain, name = core_grid_name, starts_with = pdn.GROUND, # Start with ground layer in stripes
                      pin_layers = [], generate_obstructions = [], powercell = None,
                      powercontrol = None, powercontrolnetwork = "STAR") # STAR network is common

# Find the created core grid
core_grid = pdngen.findGrid(core_grid_name)

# Add layers and connections to the core grid
for g in core_grid:
  # Make Power Rings on M7 and M8 around the core boundary
  # Prompt: width 5 um, spacing 5 um for M7 and M8 rings
  if m7 and m8:
    pdngen.makeRing(grid = g, layer0 = m7, width0 = pdn_core_ring_m7_m8_width_dbu, spacing0 = pdn_core_ring_m7_m8_spacing_dbu,
                    layer1 = m8, width1 = pdn_core_ring_m7_m8_width_dbu, spacing1 = pdn_core_ring_m7_m8_spacing_dbu,
                    starts_with = pdn.GRID, offset = core_ring_core_offset_dbu, pad_offset = core_ring_pad_offset_dbu, extend = False,
                    pad_pin_layers = [], nets = []) # Connect rings to pads/pins later if needed
    print("Core rings added on M7 and M8.")
  else:
      print("Warning: M7 or M8 layer not found for core rings. Skipping core rings.")

  # Add follow-pin connections on M1 for standard cell power/ground pins
  # Prompt: width 0.07 um
  if m1:
    pdngen.makeFollowpin(grid = g, layer = m1,
                         width = pdn_stdcell_grid_m1_width_dbu, extend = pdn.CORE) # Extend followpins to core boundary
    print("Standard cell followpins added on M1.")
  else:
    print("Warning: M1 layer not found for followpin. Skipping M1 followpin.")

  # Create horizontal/vertical straps (grids) on M4 for core (macros)
  # Prompt: width 1.2 um, spacing 1.2 um, pitch 6 um, offset 0 um
  if m4:
      pdngen.makeStrap(grid = g, layer = m4, width = pdn_macro_grid_m4_width_dbu,
                       spacing = pdn_macro_grid_m4_spacing_dbu, pitch = pdn_macro_grid_m4_pitch_dbu, offset = pdn_overall_offset_dbu,
                       number_of_straps = 0, snap = False, starts_with = pdn.GRID, extend = pdn.CORE, nets = [])
      print("Core grid straps added on M4.")
  else:
      print("Warning: M4 layer not found for core straps. Skipping M4 straps.")

  # Create horizontal/vertical straps (grids) on M7 for core (connecting to rings)
  # Prompt: width 1.4 um, spacing 1.4 um, pitch 10.8 um, offset 0 um
  if m7:
      pdngen.makeStrap(grid = g, layer = m7, width = pdn_core_strap_m7_width_dbu,
                       spacing = pdn_core_strap_m7_spacing_dbu, pitch = pdn_core_strap_m7_pitch_dbu, offset = pdn_overall_offset_dbu,
                       number_of_straps = 0, snap = False, starts_with = pdn.GRID, extend = pdn.RINGS, nets = []) # Extend straps to rings
      print("Core grid straps added on M7.")
  else:
      print("Warning: M7 layer not found for core straps. Skipping M7 straps.")

  # Connect the straps/followpins between layers
  # Prompt: via pitch 0 um, offset 0 um
  print("Adding core PDN connections...")
  if m1 and m4:
    pdngen.makeConnect(grid = g, layer0 = m1, layer1 = m4,
                       cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1], vias = [], techvias = [],
                       max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = [])
    print("  - M1 to M4 connections.")
  else:
      print("Warning: Skipping M1 to M4 connections (layers missing).")

  if m4 and m7:
    pdngen.makeConnect(grid = g, layer0 = m4, layer1 = m7,
                       cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1], vias = [], techvias = [],
                       max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = [])
    print("  - M4 to M7 connections.")
  else:
      print("Warning: Skipping M4 to M7 connections (layers missing).")

  if m7 and m8:
    # Connect M7 straps to M8 rings/straps (if M8 straps are made) and M7 rings to M8 rings
    pdngen.makeConnect(grid = g, layer0 = m7, layer1 = m8,
                       cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1], vias = [], techvias = [],
                       max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = [])
    print("  - M7 to M8 connections.")
  else:
      print("Warning: Skipping M7 to M8 connections (layers missing).")


# Create power delivery network specific for macros if they exist
# Prompt: If macros exist, build power grids for macros on M5 and M6, width 1.2 um, spacing 1.2 um, pitch 6 um, offset 0 um.
if len(macros) > 0:
  print("Adding macro-specific PDN grids on M5 and M6...")
  # Find routing layers needed for macro PDN
  m5 = design.getTech().getDB().getTech().findLayer("M5")
  m6 = design.getTech().getDB().getTech().findLayer("M6")

  if not m5 or not m6:
      print("Warning: M5 or M6 layer not found for macro PDN. Skipping macro PDN grids.")
  else:
      # Create an instance grid for each macro
      for i, macro_inst in enumerate(macros):
          macro_grid_name = f"macro_pdn_grid_{i}"
          for domain in core_domains: # Macros are typically in the core domain
              # Make an instance grid specific to this macro
              pdngen.makeInstanceGrid(domain = domain, name = macro_grid_name,
                                      starts_with = pdn.GROUND, # Start with ground layer in stripes for instance grid
                                      inst = macro_inst, halo = core_grid_halo_dbu, # Use core domain, no halo relative to macro boundary for the grid itself
                                      pg_pins_to_boundary = True, default_grid = False, # Connect to macro PG pins, not default
                                      generate_obstructions = [], is_bump = False)

          # Find the created instance grid
          macro_grid = pdngen.findGrid(macro_grid_name)

          # Add layers and connections to the macro grid
          for g in macro_grid:
              # Add horizontal/vertical straps (grids) on M5 for the macro
              # Prompt: width 1.2 um, spacing 1.2 um, pitch 6 um, offset 0 um
              pdngen.makeStrap(grid = g, layer = m5, width = pdn_macro_grid_m5_m6_width_dbu,
                              spacing = pdn_macro_grid_m5_m6_spacing_dbu, pitch = pdn_macro_grid_m5_m6_pitch_dbu, offset = pdn_overall_offset_dbu,
                              number_of_straps = 0, snap = True, starts_with = pdn.GRID, extend = pdn.CORE, nets = []) # Extend to macro boundary
              print(f"  - M5 straps added for macro {macro_inst.getName()}.")

              # Add horizontal/vertical straps (grids) on M6 for the macro
              # Prompt: width 1.2 um, spacing 1.2 um, pitch 6 um, offset 0 um
              pdngen.makeStrap(grid = g, layer = m6, width = pdn_macro_grid_m5_m6_width_dbu,
                              spacing = pdn_macro_grid_m5_m6_spacing_dbu, pitch = pdn_macro_grid_m5_m6_pitch_dbu, offset = pdn_overall_offset_dbu,
                              number_of_straps = 0, snap = True, starts_with = pdn.GRID, extend = pdn.CORE, nets = []) # Extend to macro boundary
              print(f"  - M6 straps added for macro {macro_inst.getName()}.")

              # Connect the macro grids to main core grids/rings and between themselves
              # Connect M4 <-> M5, M5 <-> M6, M6 <-> M7
              # Prompt: via pitch 0 um, offset 0 um
              print(f"  Adding connections for macro {macro_inst.getName()}...")
              if m4 and m5:
                  pdngen.makeConnect(grid = g, layer0 = m4, layer1 = m5,
                                     cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1], vias = [], techvias = [],
                                     max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = [])
                  print(f"    - M4 to M5 connections for macro {macro_inst.getName()}.")
              else:
                  print(f"Warning: Skipping M4 to M5 connections for macro {macro_inst.getName()} (layers missing).")

              if m5 and m6:
                  pdngen.makeConnect(grid = g, layer0 = m5, layer1 = m6,
                                     cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1], vias = [], techvias = [],
                                     max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = [])
                  print(f"    - M5 to M6 connections for macro {macro_inst.getName()}.")
              else:
                   print(f"Warning: Skipping M5 to M6 connections for macro {macro_inst.getName()} (layers missing).")

              if m6 and m7:
                  pdngen.makeConnect(grid = g, layer0 = m6, layer1 = m7,
                                     cut_pitch_x = pdn_cut_pitch_dbu[0], cut_pitch_y = pdn_cut_pitch_dbu[1], vias = [], techvias = [],
                                     max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = [])
                  print(f"    - M6 to M7 connections for macro {macro_inst.getName()}.")
              else:
                  print(f"Warning: Skipping M6 to M7 connections for macro {macro_inst.getName()} (layers missing).")
else:
    print("No macros found. Skipping macro-specific PDN grids.")


# Check the PDN setup for errors
print("Checking PDN setup...")
pdngen.checkSetup()
print("PDN setup check passed.")

# Build the power grids in memory
print("Building PDN grids...")
pdngen.buildGrids(False) # False means don't check for uniqueness (sometimes needed for complex grids)
print("PDN grids built.")

# Write the built grids to the database (creates actual shapes)
print("Writing PDN grids to database...")
pdngen.writeToDb(True) # True means skip checking uniqueness
print("PDN grids written to database.")

# Reset the internal shapes representation
pdngen.resetShapes()

# Dump DEF after Power Planning
design.writeDef(outputDir / "pdn.def")
print(f"Dumped DEF: {outputDir / 'pdn.def'}")

# --- Global Routing ---
print("Performing global routing...")
# Get the TritonRoute global router object
grt = design.getGlobalRouter()

# Find the routing levels for signal and clock nets
# Using M1-M7 for both as per common practice and layer availability checked earlier
if not m1 or not m7:
    print("Error: M1 or M7 layer not found for global routing range.")
    exit(1)

signal_low_layer_level = m1.getRoutingLevel()
signal_high_layer_level = m7.getRoutingLevel()
clk_low_layer_level = m1.getRoutingLevel()
clk_high_layer_level = m7.getRoutingLevel()

# Set the minimum and maximum routing layers for signals
grt.setMinRoutingLayer(signal_low_layer_level)
grt.setMaxRoutingLayer(signal_high_layer_level)
# Set the minimum and maximum routing layers for clock nets
grt.setMinLayerForClock(clk_low_layer_level)
grt.setMaxLayerForClock(clk_high_layer_level)

# Set the congestion adjustment factor (higher value reduces congestion)
grt.setAdjustment(global_router_adjustment) # Common value, adjust based on congestion results
# Enable verbose output for global routing
grt.setVerbose(True)

# Perform global routing (True means run with timing analysis enabled)
grt.globalRoute(True)
print("Global routing finished.")

# Dump DEF after Global Routing (Optional, GR often doesn't add shapes visible in DEF)
# design.writeDef(outputDir / "global_routing.def")
# print(f"Dumped DEF: {outputDir / 'global_routing.def'}")


# --- Detailed Routing ---
print("Performing detailed routing...")
# Get the TritonRoute detailed router object
drter = design.getTritonRoute()
# Get detailed router parameters structure
params = drt.ParamStruct()

# Set various detailed routing parameters
# Output file paths (can be left empty to disable)
params.outputMazeFile = ""
params.outputDrcFile = outputDir.as_posix() + "/drc.rpt" # Example: Output DRC report
params.outputCmapFile = ""
params.outputGuideCoverageFile = ""
# Technology process node (optional)
params.dbProcessNode = ""
# Enable via generation during routing
params.enableViaGen = True
# Number of detailed routing iterations (typically 1 is sufficient after good global route)
params.drouteEndIter = detailed_router_end_iter
# Via-in-pin layers (leave empty to use defaults or tech file)
params.viaInPinBottomLayer = ""
params.viaInPinTopLayer = ""
# Orthogonal routing parameters (leave default)
params.orSeed = -1
params.orK = 0

# Set the bottom and top routing layers for detailed routing
params.bottomRoutingLayer = detailed_router_bottom_layer
params.topRoutingLayer = detailed_router_top_layer

# Set verbosity level
params.verbose = 1
# Clean patches after routing (often fixes minor issues)
params.cleanPatches = True
# Perform post-route antenna fixing (Passive Antenna)
params.doPa = True
# Single step detailed routing mode (False for standard run)
params.singleStepDR = False
# Minimum access points for pin connections
params.minAccessPoints = 1
# Save guide updates (debugging feature)
params.saveGuideUpdates = False

# Set the detailed router parameters
drter.setParams(params)
# Run the detailed router
drter.main()
print("Detailed routing finished.")

# Dump the final DEF file
design.writeDef(outputDir / "final.def")
print(f"Dumped DEF: {outputDir / 'final.def'}")

print("\nOpenROAD flow completed.")

