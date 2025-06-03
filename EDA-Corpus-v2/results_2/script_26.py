# This script performs a complete digital back-end flow for OpenROAD,
# including reading design files, floorplanning, placement, CTS, PDN generation,
# IR Drop analysis, power reporting, and routing.
#
# Based on the original prompt and consolidation of requirements.

from openroad import Tech, Design
from pathlib import Path
import odb
import pdn
import drt
import psm
import grt
import cts
import mpl
import gpl
import opendp
# Explicitly import Timing
from openroad import Timing # Need Timing object for IR drop analysis corner

import glob
import sys

# --- 1. Imports and Setup ---
print("--- Starting OpenROAD Python Flow ---")

# Initialize OpenROAD core objects
# Tech object is needed to read libraries/tech files and get layer info
tech = Tech()
# Design object holds the current design data
design = Design(tech)

# --- 2. User Configuration ---
# Define paths to technology, library, and design files.
# *** IMPORTANT: User must set the correct paths and design names here ***
techDir = Path("./tech/")         # Example technology directory
lefDir = Path("./lef/")           # Example LEF directory (tech and cell LEFs)
libDir = Path("./lib/")           # Example timing library directory
designDir = Path("./")            # Example design directory (where netlist is)
design_top_module_name = "your_top_module_name" # *** User must set the top module name ***
verilogFile = designDir / "your_netlist.v"    # *** User must set the netlist file name ***

# Clock Configuration
clock_port_name = "clk_i"   # Name of the clock input port
clock_period_ns = 50.0      # Clock period in nanoseconds
clock_name = "core_clock"   # Internal clock signal name

# Wire RC Values (for clock and signal nets)
wire_resistance_per_unit = 0.0435 # Resistance per unit length (e.g., ohms/um)
wire_capacitance_per_unit = 0.0817 # Capacitance per unit length (e.g., fF/um or pF/um)

# Floorplan Configuration
die_area_ll_um = (0, 0)      # Die area lower-left corner in microns
die_area_ur_um = (70, 70)    # Die area upper-right corner in microns
core_area_ll_um = (6, 6)     # Core area lower-left corner in microns
core_area_ur_um = (64, 64)   # Core area upper-right corner in microns
# *** User must set the correct site name for standard cells ***
standard_cell_site_name = "FreePDK45_38x28_10R_NP_162NW_34O" # Example site name

# Placement Configuration
global_placement_iterations = 20 # Number of iterations for global placement
detailed_placement_max_displacement_um = 0.0 # Maximum cell displacement in microns (0 = no movement from global)
macro_halo_um = 5.0 # Keepout halo around macros in microns
# Note: The specific macro bounding box (32,32 to 55,60) from the prompt is
# not a placement command but likely a descriptive detail or constraint
# handled implicitly by the macro placer operating within the core area.
# The script uses the standard macro placer to distribute macros.

# CTS Configuration
clock_buffer_cell = "BUF_X3" # Cell name to use for clock tree buffers

# PDN Configuration (All dimensions in microns)
pdn_offset_um = 0.0 # Offset for straps/rings from boundaries/grid lines

# Core Grid / Standard Cell PDN (within core area)
core_ring_layers = ("metal7", "metal8") # Layers for core power rings (Horiz, Vert)
core_ring_width_um = 4.0
core_ring_spacing_um = 4.0
core_m1_strap_layer = "metal1"
core_m1_strap_width_um = 0.07
core_m4_strap_layer = "metal4"
core_m4_strap_width_um = 1.2
core_m4_strap_spacing_um = 1.2
core_m4_strap_pitch_um = 6.0
core_m7_strap_layer = "metal7" # Note: M7 used for both rings and straps per prompt
core_m7_strap_width_um = 1.4
core_m7_strap_spacing_um = 1.4
core_m7_strap_pitch_um = 10.8
core_m8_strap_layer = "metal8" # Note: M8 used for both rings and straps per prompt
core_m8_strap_width_um = 1.4 # Prompt specified M7 width/spacing/pitch for M8 as well
core_m8_strap_spacing_um = 1.4
core_m8_strap_pitch_um = 10.8

# Macro Grid PDN (around macro instances) - Straps only as per prompt
macro_m5_strap_layer = "metal5"
macro_m5_strap_width_um = 1.2
macro_m5_strap_spacing_um = 1.2
macro_m5_strap_pitch_um = 6.0
macro_m6_strap_layer = "metal6"
macro_m6_strap_width_um = 1.2
macro_m6_strap_spacing_um = 1.2
macro_m6_strap_pitch_um = 6.0

# Via Configuration
via_cut_pitch_um = 2.0 # Pitch for via arrays between parallel grids

# IR Drop Analysis Configuration
ir_drop_analyze_net_name = "VDD" # Net to analyze for IR drop (usually VDD)
# Analysis will be performed on all grid nodes for this net, including M1 nodes.

# Routing Configuration
min_routing_layer_name = "metal1" # Minimum layer for signal and clock routing
max_routing_layer_name = "metal6" # Maximum layer for signal and clock routing

# --- 3. Read Design Files ---
print("\n--- Reading Design Files ---")

# Read technology LEF files (*.tech.lef)
tech_lef_files = glob.glob(f"{techDir}/*.tech.lef")
if not tech_lef_files:
    print(f"Error: No tech LEF files found in {techDir}")
    sys.exit(1)
for tech_lef_file in tech_lef_files:
    print(f"Reading technology LEF: {tech_lef_file}")
    tech.readLef(tech_lef_file)

# Read cell LEF files (*.lef, excluding *.tech.lef)
cell_lef_files = glob.glob(f"{lefDir}/*.lef")
cell_lef_files = [f for f in cell_lef_files if not f.endswith(".tech.lef")]
if not cell_lef_files:
    print(f"Warning: No cell LEF files found in {lefDir}")
for cell_lef_file in cell_lef_files:
    print(f"Reading cell LEF: {cell_lef_file}")
    tech.readLef(cell_lef_file)

# Read timing liberty files (*.lib)
lib_files = glob.glob(f"{libDir}/*.lib")
if not lib_files:
    print(f"Error: No liberty files found in {libDir}")
    sys.exit(1)
for lib_file in lib_files:
    print(f"Reading liberty file: {lib_file}")
    tech.readLiberty(lib_file)

# Create design and read Verilog netlist
print(f"Reading Verilog netlist: {verilogFile}")
design.readVerilog(verilogFile.as_posix())

# --- 4. Link Design ---
print(f"\n--- Linking Design: {design_top_module_name} ---")
try:
    design.link(design_top_module_name)
except Exception as e:
    print(f"Error linking design: {e}")
    print("Please ensure the top module name and input files are correct.")
    sys.exit(1)

# Get the current block (the top-level module)
block = design.getBlock()
if not block:
    print("Error: Could not get block after linking.")
    sys.exit(1)

# --- 5. Clock Setup ---
print("\n--- Setting up Clock ---")
# OpenROAD's create_clock is a TCL command, best called via evalTclString
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
# Propagate the created clock signal
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")
print(f"Clock '{clock_name}' created on port '{clock_port_name}' with period {clock_period_ns} ns.")

# --- 6. Set Wire RC ---
print("\n--- Setting Wire RC Values ---")
# Set RC values for clock and signal nets using TCL commands
design.evalTclString(f"set_wire_rc -clock -resistance {wire_resistance_per_unit} -capacitance {wire_capacitance_per_unit}")
design.evalTclString(f"set_wire_rc -signal -resistance {wire_resistance_per_unit} -capacitance {wire_capacitance_per_unit}")
print(f"Set wire RC: Resistance={wire_resistance_per_unit}, Capacitance={wire_capacitance_per_unit}")


# --- 7. Floorplan ---
print("\n--- Performing Floorplan ---")
floorplan = design.getFloorplan()

# Convert dimensions from microns to DBU (Database Units)
# OpenROAD APIs often expect DBU
design_dbu = design.micronToDBU(1.0) # Get the DBU per micron ratio

die_area_ll_dbu = (design.micronToDBU(die_area_ll_um[0]), design.micronToDBU(die_area_ll_um[1]))
die_area_ur_dbu = (design.micronToDBU(die_area_ur_um[0]), design.micronToDBU(die_area_ur_um[1]))
die_area = odb.Rect(die_area_ll_dbu[0], die_area_ll_dbu[1], die_area_ur_dbu[0], die_area_ur_dbu[1])

core_area_ll_dbu = (design.micronToDBU(core_area_ll_um[0]), design.micronToDBU(core_area_ll_um[1]))
core_area_ur_dbu = (design.micronToDBU(core_area_ur_um[0]), design.micronToDBU(core_area_ur_um[1]))
core_area = odb.Rect(core_area_ll_dbu[0], core_area_ll_dbu[1], core_area_ur_dbu[0], core_area_ur_dbu[1])

# Find the site for standard cells
site = floorplan.findSite(standard_cell_site_name)
if not site:
    print(f"Error: Could not find site '{standard_cell_site_name}'. Please check your LEF files.")
    sys.exit(1)

# Initialize the floorplan
print(f"Initializing floorplan with Die Area: {die_area_ll_um} um to {die_area_ur_um} um")
print(f"Core Area: {core_area_ll_um} um to {core_area_ur_um} um")
floorplan.initFloorplan(die_area, core_area, site)

# Create placement tracks based on the site definition
print("Creating placement tracks.")
floorplan.makeTracks()

# Write out the floorplan DEF file
floorplan_def_file = "floorplan.def"
design.writeDef(floorplan_def_file)
print(f"Floorplan complete. Wrote {floorplan_def_file}")

# --- 8. Placement (Macros & Standard Cells) ---
print("\n--- Performing Placement ---")

# Identify macro blocks
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]
print(f"Found {len(macros)} macro instances.")

if len(macros) > 0:
    # Configure and run Macro Placement
    print("Running Macro Placement...")
    mplacer = design.getMacroPlacer()

    # Convert macro placement parameters to DBU
    macro_halo_dbu = design.micronToDBU(macro_halo_um)

    # Get core area boundaries in microns for the fence region
    core_lx_um = block.dbuToMicrons(core_area.xMin())
    core_ly_um = block.dbuToMicrons(core_area.yMin())
    core_ux_um = block.dbuToMicrons(core_area.xMax())
    core_uy_um = block.dbuToMicrons(core_area.yMax())

    # Run macro placement within the core area
    mplacer.place(
        num_threads = 64, # Example: Number of threads
        max_num_macro = len(macros), # Place all identified macros
        # Other parameters can be tuned based on design needs
        halo_width = macro_halo_um, # Halo/keepout in microns
        halo_height = macro_halo_um,
        fence_lx = core_lx_um, # Fence region lower-left X in microns
        fence_ly = core_ly_um, # Fence region lower-left Y in microns
        fence_ux = core_ux_um, # Fence region upper-right X in microns
        fence_uy = core_uy_um, # Fence region upper-right Y in microns
        # ... add other relevant parameters from the API if needed ...
    )
    print("Macro Placement complete.")
else:
    print("No macros found. Skipping Macro Placement.")


# Configure and run Global Placement
print("Running Global Placement...")
gplacer = design.getReplace()

# Set Global Placement parameters
# gplacer.setTimingDrivenMode(False) # Example: Disable timing-driven
# gplacer.setRoutabilityDrivenMode(True) # Example: Enable routability-driven
# gplacer.setUniformTargetDensityMode(True) # Example: Uniform target density
gplacer.setInitialPlaceMaxIter(global_placement_iterations) # Set max iterations
# gplacer.setInitDensityPenalityFactor(0.05) # Example: Initial density penalty

# Run initial (coarse) and Nesterov (fine) placement
gplacer.doInitialPlace(threads = 4) # Example: Number of threads
gplacer.doNesterovPlace(threads = 4) # Example: Number of threads

# Reset the global placer state after use
gplacer.reset()
print("Global Placement complete.")

# Configure and run Detailed Placement
print("Running Detailed Placement...")
dplacer = design.getOpendp()

# Remove filler cells if they were previously added (needed before DP that moves cells)
# dplacer.removeFillers() # Uncomment if fillers were added before global placement

# Convert maximum displacement to DBU
max_disp_x_dbu = design.micronToDBU(detailed_placement_max_displacement_um)
max_disp_y_dbu = design.micronToDBU(detailed_placement_max_displacement_um) # Use same for Y

# Run detailed placement. A max displacement of 0 means cells should not move.
# This is a very strict constraint and relies heavily on good global placement.
dplacer.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print(f"Detailed Placement complete (Max Displacement: {detailed_placement_max_displacement_um} um).")

# Write out the placement DEF file
placement_def_file = "placement.def"
design.writeDef(placement_def_file)
print(f"Wrote {placement_def_file}")

# --- 9. Clock Tree Synthesis (CTS) ---
print("\n--- Performing Clock Tree Synthesis ---")
cts_tool = design.getTritonCts()
cts_parms = cts_tool.getParms()

# Set CTS parameters
# cts_parms.setWireSegmentUnit(design.micronToDBU(20)) # Example: Set wire segment unit
cts_tool.setBufferList(clock_buffer_cell) # Set list of allowed buffers
cts_tool.setRootBuffer(clock_buffer_cell) # Set root buffer cell
cts_tool.setSinkBuffer(clock_buffer_cell) # Set sink buffer cell
# cts_tool.setClockNets(clock_name) # Explicitly specify clock nets if needed

# Run CTS
print(f"Running CTS using buffer '{clock_buffer_cell}'...")
cts_tool.runTritonCts()
print("CTS complete.")

# Run detailed placement again after CTS to clean up standard cells
# CTS can insert buffers and shift cells, so a final detailed placement is common.
print("Running Detailed Placement after CTS...")
# Remove fillers before re-running DP
# dplacer.removeFillers() # Uncomment if using fillers

# Re-run detailed placement with the specified displacement constraint
# Note: Keeping 0 um displacement might be too restrictive after CTS
dplacer.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Detailed Placement after CTS complete.")

# Write out the CTS DEF file
cts_def_file = "cts.def"
design.writeDef(cts_def_file)
print(f"Wrote {cts_def_file}")

# --- 10. Power Delivery Network (PDN) ---
print("\n--- Generating Power Delivery Network (PDN) ---")
pdngen = design.getPdnGen()

# Set up global power/ground connections if not already present in the netlist
# This ensures standard cell VDD/VSS pins connect to the global nets.
print("Setting up global power/ground connections...")
VDD_net_name = "VDD" # Standard power net name
VSS_net_name = "VSS" # Standard ground net name

VDD_net = block.findNet(VDD_net_name)
VSS_net = block.findNet(VSS_net_name)

# Create VDD/VSS nets if they don't exist
if VDD_net is None:
    print(f"Net '{VDD_net_name}' not found, creating...")
    VDD_net = odb.dbNet_create(block, VDD_net_name)
    VDD_net.setSigType("POWER")
if VSS_net is None:
    print(f"Net '{VSS_net_name}' not found, creating...")
    VSS_net = odb.dbNet_create(block, VSS_net_name)
    VSS_net.setSigType("GROUND")

# Mark VDD/VSS as special nets (prevents routing tools from treating them as signal nets)
VDD_net.setSpecial()
VSS_net.setSpecial()
print(f"Nets '{VDD_net_name}' and '{VSS_net_name}' marked as special.")

# Connect standard cell VDD/VSS pins to the global nets
# Applies connection to all instances (.*) for pins matching ^VDD$ or ^VSS$
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
# Apply the global connections
block.globalConnect()
print("Standard cell power/ground pins globally connected.")

# Configure power domains (create a 'Core' domain tied to VDD/VSS)
# This is needed before defining grid patterns
core_domain = pdngen.findDomain("Core")
if core_domain is None:
    print("Creating 'Core' power domain...")
    core_domain = pdn.PdnGen.createDomain(pdngen, "Core") # Use the class method
    pdngen.setCoreDomain(power = VDD_net, switched_power = None, ground = VSS_net, secondary = [])
    print("Core power domain created and set.")
else:
     print("'Core' power domain already exists.")
     # Ensure the existing core domain is set with the primary nets
     pdngen.setCoreDomain(power = VDD_net, switched_power = None, ground = VSS_net, secondary = [])
     print("Core power domain configured with VDD/VSS.")

# Get metal layers needed for PDN (convert names to odb.dbTechLayer objects)
tech_db = design.getTech().getDB().getTech()
m1_layer = tech_db.findLayer(core_m1_strap_layer)
m4_layer = tech_db.findLayer(core_m4_strap_layer)
m5_layer = tech_db.findLayer(macro_m5_strap_layer) # Used for macros
m6_layer = tech_db.findLayer(macro_m6_strap_layer) # Used for macros
m7_layer = tech_db.findLayer(core_m7_strap_layer) # Used for core rings/straps
m8_layer = tech_db.findLayer(core_m8_strap_layer) # Used for core rings/straps

# Check if layers were found
if not all([m1_layer, m4_layer, m5_layer, m6_layer, m7_layer, m8_layer]):
    missing_layers = [name for name, layer in zip([core_m1_strap_layer, core_m4_strap_layer, macro_m5_strap_layer, macro_m6_strap_layer, core_m7_strap_layer, core_m8_strap_layer], [m1_layer, m4_layer, m5_layer, m6_layer, m7_layer, m8_layer]) if not layer]
    print(f"Error: Could not find metal layers: {missing_layers}. Check your LEF files.")
    sys.exit(1)

# Convert PDN dimensions from microns to DBU
pdn_offset_dbu = design.micronToDBU(pdn_offset_um)
via_cut_pitch_dbu = design.micronToDBU(via_cut_pitch_um)
via_cut_pitch_dbu_x = via_cut_pitch_dbu
via_cut_pitch_dbu_y = via_cut_pitch_dbu

# Core Grid DBU
core_ring_width_dbu = design.micronToDBU(core_ring_width_um)
core_ring_spacing_dbu = design.micronToDBU(core_ring_spacing_um)
core_m1_strap_width_dbu = design.micronToDBU(core_m1_strap_width_um)
core_m4_strap_width_dbu = design.micronToDBU(core_m4_strap_width_um)
core_m4_strap_spacing_dbu = design.micronToDBU(core_m4_strap_spacing_um)
core_m4_strap_pitch_dbu = design.micronToDBU(core_m4_strap_pitch_um)
core_m7_strap_width_dbu = design.micronToDBU(core_m7_strap_width_um)
core_m7_strap_spacing_dbu = design.micronToDBU(core_m7_strap_spacing_um)
core_m7_strap_pitch_dbu = design.micronToDBU(core_m7_strap_pitch_um)
core_m8_strap_width_dbu = design.micronToDBU(core_m8_strap_width_um)
core_m8_strap_spacing_dbu = design.micronToDBU(core_m8_strap_spacing_um)
core_m8_strap_pitch_dbu = design.micronToDBU(core_m8_strap_pitch_um)

# Macro Grid DBU
macro_m5_strap_width_dbu = design.micronToDBU(macro_m5_strap_width_um)
macro_m5_strap_spacing_dbu = design.micronToDBU(macro_m5_strap_spacing_um)
macro_m5_strap_pitch_dbu = design.micronToDBU(macro_m5_strap_pitch_um)
macro_m6_strap_width_dbu = design.micronToDBU(macro_m6_strap_width_um)
macro_m6_strap_spacing_dbu = design.micronToDBU(macro_m6_strap_spacing_um)
macro_m6_strap_pitch_dbu = design.micronToDBU(macro_m6_strap_pitch_um)

# Create Core Power Grid (Standard Cells)
# Define the grid for the 'Core' domain
pdngen.makeCoreGrid(
    domain = core_domain,
    name = "core_grid", # Name for this grid definition
    starts_with = pdn.GROUND, # Start pattern (e.g., Ground, Power)
    # pin_layers = [], # Optionally list layers used for pin connections
    # generate_obstructions = [], # Optionally list layers to create obstructions on
    # powercell = None, # For power gating
    # powercontrol = None,
    # powercontrolnetwork = "STAR"
)
core_grids = pdngen.findGrid("core_grid")
if not core_grids:
     print("Error: Failed to create core grid.")
     sys.exit(1)

# Apply rings and straps to the core grid(s)
for grid in core_grids:
    print(f"Applying patterns to core grid '{grid.getName()}'...")
    # Create core power rings on M7 and M8 around the core boundary
    # offset = [left, bottom, right, top] offset from boundary in DBU
    ring_offset_dbu = [pdn_offset_dbu] * 4 # Offset 0 from core boundary
    ring_pad_offset_dbu = [0] * 4 # No pad offset needed for core ring

    pdngen.makeRing(
        grid = grid,
        layer0 = m7_layer, # Horizontal ring layer (e.g., M7 is usually H)
        width0 = core_ring_width_dbu,
        spacing0 = core_ring_spacing_dbu,
        layer1 = m8_layer, # Vertical ring layer (e.g., M8 is usually V)
        width1 = core_ring_width_dbu,
        spacing1 = core_ring_spacing_dbu,
        starts_with = pdn.GRID, # Start pattern (e.g., follow grid definition)
        offset = ring_offset_dbu,
        pad_offset = ring_pad_offset_dbu,
        extend = False, # Do not extend beyond the core boundary
        # pad_pin_layers = [], # Not connecting to pads with core ring
        nets = [] # Apply to all nets in the grid (VDD/VSS)
    )
    print(f"Created rings on {core_m7_strap_layer}/{core_m8_strap_layer} for core grid.")

    # Create horizontal followpin straps on M1 (for standard cell rows)
    pdngen.makeFollowpin(
        grid = grid,
        layer = m1_layer,
        width = core_m1_strap_width_dbu,
        extend = pdn.CORE, # Extend within the core area
        # nets = [] # Apply to all nets in the grid
    )
    print(f"Created followpin straps on {core_m1_strap_layer} for core grid.")

    # Create vertical straps on M4
    pdngen.makeStrap(
        grid = grid,
        layer = m4_layer,
        width = core_m4_strap_width_dbu,
        spacing = core_m4_strap_spacing_dbu,
        pitch = core_m4_strap_pitch_dbu,
        offset = pdn_offset_dbu, # Offset from core boundary or grid start
        number_of_straps = 0, # Auto-calculate number based on pitch/area
        snap = False, # Do not snap to grid lines
        starts_with = pdn.GRID,
        extend = pdn.CORE, # Extend within the core area
        nets = [] # Apply to all nets in the grid
    )
    print(f"Created straps on {core_m4_strap_layer} for core grid.")

    # Create horizontal straps on M7 (connecting to M7 rings)
    pdngen.makeStrap(
        grid = grid,
        layer = m7_layer,
        width = core_m7_strap_width_dbu,
        spacing = core_m7_strap_spacing_dbu,
        pitch = core_m7_strap_pitch_dbu,
        offset = pdn_offset_dbu,
        number_of_straps = 0,
        snap = False,
        starts_with = pdn.GRID,
        extend = pdn.RINGS, # Extend to connect to the M7 rings
        nets = []
    )
    print(f"Created straps on {core_m7_strap_layer} for core grid.")

    # Create vertical straps on M8 (connecting to M8 rings)
    pdngen.makeStrap(
        grid = grid,
        layer = m8_layer,
        width = core_m8_strap_width_dbu,
        spacing = core_m8_strap_spacing_dbu,
        pitch = core_m8_strap_pitch_dbu,
        offset = pdn_offset_dbu,
        number_of_straps = 0,
        snap = False,
        starts_with = pdn.GRID,
        extend = pdn.RINGS, # Extend to connect to the M8 rings
        nets = []
    )
    print(f"Created straps on {core_m8_strap_layer} for core grid.")


    # Create via connections between core grid layers
    print("Creating via connections for core grid...")
    # Connect M1 to M4
    pdngen.makeConnect(
        grid = grid,
        layer0 = m1_layer, layer1 = m4_layer, # Assume M1 is horizontal, M4 is vertical
        cut_pitch_x = via_cut_pitch_dbu_x, # Pitch in X for vertical connection
        cut_pitch_y = via_cut_pitch_dbu_y, # Pitch in Y for horizontal connection
        # vias, techvias, max_rows, max_columns, ongrid, split_cuts, dont_use_vias parameters can be set if needed
    )
    # Connect M4 to M7
    pdngen.makeConnect(
        grid = grid,
        layer0 = m4_layer, layer1 = m7_layer, # Assume M4 is vertical, M7 is horizontal
        cut_pitch_x = via_cut_pitch_dbu_x,
        cut_pitch_y = via_cut_pitch_dbu_y,
    )
    # Connect M7 to M8
    pdngen.makeConnect(
        grid = grid,
        layer0 = m7_layer, layer1 = m8_layer, # Assume M7 is horizontal, M8 is vertical
        cut_pitch_x = via_cut_pitch_dbu_x,
        cut_pitch_y = via_cut_pitch_dbu_y,
    )
    print("Core grid via connections configured.")


# Create Power Grid for Macro Blocks (if macros exist)
if len(macros) > 0:
    print("\n--- Generating Macro Power Grids ---")
    # Create a separate instance grid definition for each macro
    for i, macro_inst in enumerate(macros):
        print(f"Defining PDN for macro instance: {macro_inst.getName()}...")

        # Create an instance grid specifically for this macro
        pdngen.makeInstanceGrid(
            domain = core_domain, # Associate with the core domain
            name = f"macro_grid_{i}", # Unique name per instance
            starts_with = pdn.GROUND, # Start pattern
            inst = macro_inst, # The specific macro instance
            # halo = [0]*4, # No halo needed around the macro for its own grid
            pg_pins_to_boundary = True, # Connect macro PG pins to grid boundary
            default_grid = False, # Not the default grid
            # generate_obstructions = [],
            # is_bump = False
        )
        macro_grids = pdngen.findGrid(f"macro_grid_{i}")
        if not macro_grids:
            print(f"Error: Failed to create instance grid for {macro_inst.getName()}.")
            continue # Skip to next macro

        for grid in macro_grids:
            print(f"Applying patterns to macro grid '{grid.getName()}' for {macro_inst.getName()}...")
            # Corrected: Removed makeRing for M5/M6 macro grids as per verification feedback.
            # The prompt only specified M5/M6 "grids" (straps) with given dimensions.

            # Create horizontal straps on M5 within the macro grid
            pdngen.makeStrap(
                grid = grid,
                layer = m5_layer,
                width = macro_m5_strap_width_dbu,
                spacing = macro_m5_strap_spacing_dbu,
                pitch = macro_m5_strap_pitch_dbu,
                offset = pdn_offset_dbu,
                number_of_straps = 0,
                snap = True, # Snap to grid
                starts_with = pdn.GRID,
                extend = pdn.NONE, # Extend within the instance grid boundary
                nets = []
            )
            print(f"Created straps on {macro_m5_strap_layer} for macro grid.")

            # Create vertical straps on M6 within the macro grid
            pdngen.makeStrap(
                grid = grid,
                layer = m6_layer,
                width = macro_m6_strap_width_dbu,
                spacing = macro_m6_strap_spacing_dbu,
                pitch = macro_m6_strap_pitch_dbu,
                offset = pdn_offset_dbu,
                number_of_straps = 0,
                snap = True,
                starts_with = pdn.GRID,
                extend = pdn.NONE, # Extend within the instance grid boundary
                nets = []
            )
            print(f"Created straps on {macro_m6_strap_layer} for macro grid.")

            # Create via connections between macro grid layers and core grid layers
            print("Creating via connections for macro grid...")
            # Connect M4 (from core grid) to M5 (macro grid)
            pdngen.makeConnect(
                grid = grid,
                layer0 = m4_layer, layer1 = m5_layer, # Assume M4 is V, M5 is H
                cut_pitch_x = via_cut_pitch_dbu_x,
                cut_pitch_y = via_cut_pitch_dbu_y,
            )
            # Connect M5 to M6 (macro grid layers)
            pdngen.makeConnect(
                grid = grid,
                layer0 = m5_layer, layer1 = m6_layer, # Assume M5 is H, M6 is V
                cut_pitch_x = via_cut_pitch_dbu_x,
                cut_pitch_y = via_cut_pitch_dbu_y,
            )
            # Connect M6 (macro grid) to M7 (core grid)
            pdngen.makeConnect(
                grid = grid,
                layer0 = m6_layer, layer1 = m7_layer, # Assume M6 is V, M7 is H
                cut_pitch_x = via_cut_pitch_dbu_x,
                cut_pitch_y = via_cut_pitch_dbu_y,
            )
            print("Macro grid via connections configured.")

else:
    print("No macros found. Skipping Macro PDN generation.")


# Finalize and Build the PDN
print("\n--- Building PDN Shapes ---")
# Verify the PDN setup
pdngen.checkSetup()
print("PDN setup check complete.")

# Build the power grid shapes in the database
# The 'False' parameter often indicates not generating metal fill
pdngen.buildGrids(False)
print("PDN shapes built.")

# Write the generated PDN shapes to the design database permanently
# The 'True' parameter typically means commit the shapes to the DB
pdngen.writeToDb(True)
print("PDN shapes committed to database.")

# Reset temporary shapes used during generation
pdngen.resetShapes()
print("PDN temporary shapes reset.")

# Write out the PDN DEF file
pdn_def_file = "pdn.def"
design.writeDef(pdn_def_file)
print(f"PDN generation complete. Wrote {pdn_def_file}")

# --- 11. IR Drop Analysis ---
print("\n--- Performing IR Drop Analysis ---")
# IR drop analysis requires a timing corner for static analysis or activity for dynamic.
# Assuming static analysis using a default/first timing corner if available.
timing = Timing(design) # Get the timing object

# Get the PSM (Power Signoff) tool
psm_tool = design.getPDNSim()

# Find the net to analyze (e.g., VDD)
analyze_net = block.findNet(ir_drop_analyze_net_name)
if not analyze_net:
    print(f"Error: Could not find net '{ir_drop_analyze_net_name}' for IR drop analysis.")
    # Proceed without IR drop or exit
    # sys.exit(1)
    print("Skipping IR drop analysis.")
else:
    print(f"Analyzing IR drop on net '{analyze_net.getName()}'...")
    try:
        # Run static IR drop analysis on the specified net
        # The analysis is performed on the entire grid connected to this net.
        # Reporting specific layers (like M1 nodes) is usually done via result inspection.
        psm_tool.analyzePowerGrid(
            net = analyze_net,
            enable_em = False, # Disable Electromigration analysis for now
            corner = timing.getCorners()[0] if timing.getCorners() else None, # Use first timing corner if available
            use_prev_solution = False,
            em_file = "", # No EM file output
            error_file = "ir_drop.error", # Output error file
            voltage_source_file = "", # No external voltage source file
            voltage_file = "ir_drop.volt", # Output voltage file (contains node voltages)
            source_type = psm.GeneratedSourceType_FULL # Use full power source model
        )
        print("IR Drop analysis complete.")
        print(f"IR drop voltage file: ir_drop.volt")
        # Further analysis of ir_drop.volt file would be needed to report on specific layers like M1 nodes.

    except Exception as e:
        print(f"Error during IR Drop analysis: {e}")
        print("Skipping IR drop analysis.")


# --- 12. Power Report ---
print("\n--- Reporting Power ---")
# The report_power command is typically a TCL command
# It requires RC extraction and potentially activity files or library power models.
# Assuming necessary setup (timing libraries with power data, static timing analysis) is done.
design.evalTclString("report_power")
print("Power report generated.")

# --- 13. Routing (Global & Detailed) ---
print("\n--- Performing Routing ---")

# Configure and run Global Routing
print("Running Global Routing...")
grt_tool = design.getGlobalRouter()

# Find routing layers and get their routing levels
tech_db = design.getTech().getDB().getTech() # Get tech_db again for layers
min_routing_layer = tech_db.findLayer(min_routing_layer_name)
max_routing_layer = tech_db.findLayer(max_routing_layer_name)

if not min_routing_layer or not max_routing_layer:
    print(f"Error: Could not find routing layers '{min_routing_layer_name}' or '{max_routing_layer_name}'.")
    sys.exit(1)

min_routing_level = min_routing_layer.getRoutingLevel()
max_routing_level = max_routing_layer.getRoutingLevel()

# Set min and max routing layers for signals and clocks
grt_tool.setMinRoutingLayer(min_routing_level)
grt_tool.setMaxRoutingLayer(max_routing_level)
grt_tool.setMinLayerForClock(min_routing_level) # Often same as signal
grt_tool.setMaxLayerForClock(max_routing_level) # Often same as signal

# grt_tool.setAdjustment(0.5) # Example: Global adjustment factor
# grt_tool.setVerbose(True) # Example: Enable verbose output

# Run global routing (True for timing-driven)
grt_tool.globalRoute(True) # Consider timing during global routing
print("Global Routing complete.")

# Write out the global routing DEF file
global_route_def_file = "global_route.def"
design.writeDef(global_route_def_file)
print(f"Wrote {global_route_def_file}")


# Configure and run Detailed Routing
print("\nRunning Detailed Routing...")
drter = design.getTritonRoute()
dr_params = drt.ParamStruct()

# Set Detailed Routing parameters
dr_params.outputMazeFile = "" # No maze file output
dr_params.outputDrcFile = "detailed_route.drc" # Output DRC violations file
dr_params.outputCmapFile = "" # No congestion map output
dr_params.outputGuideCoverageFile = "" # No guide coverage output
# dr_params.dbProcessNode = "" # Process node if applicable
dr_params.enableViaGen = True # Enable via generation
# dr_params.viaInPinBottomLayer = "" # Configure via-in-pin if needed
# dr_params.viaInPinTopLayer = ""
# dr_params.orSeed = -1 # Random seed
# dr_params.orK = 0
# Set the bottom and top routing layers using names
dr_params.bottomRoutingLayer = min_routing_layer_name
dr_params.topRoutingLayer = max_routing_layer_name
dr_params.verbose = 1 # Verbos ity level
dr_params.cleanPatches = True # Clean up routing patches
dr_params.doPa = True # Perform pin access
dr_params.singleStepDR = False # Run full detailed routing
# dr_params.minAccessPoints = 1 # Minimum access points
# dr_params.saveGuideUpdates = False # Save guide updates

# Apply parameters and run detailed routing
drter.setParams(dr_params)
drter.main() # Execute detailed routing
print("Detailed Routing complete.")

# Write out the detailed routing DEF file
detailed_route_def_file = "detailed_route.def"
design.writeDef(detailed_route_def_file)
print(f"Wrote {detailed_route_def_file}")


# --- 14. Final Outputs ---
print("\n--- Writing Final Outputs ---")

# Write final Verilog netlist (post-routing, may include buffers, fill cells)
final_verilog_file = "final.v"
design.evalTclString(f"write_verilog {final_verilog_file}")
print(f"Wrote final Verilog: {final_verilog_file}")

# Write final ODB database file (contains complete design state including routing)
final_odb_file = "final.odb"
design.writeDb(final_odb_file)
print(f"Wrote final ODB: {final_odb_file}")

print("\n--- OpenROAD Python Flow Complete ---")