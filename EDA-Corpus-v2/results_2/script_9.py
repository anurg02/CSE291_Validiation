# -*- coding: utf-8 -*-
###############################################################################
# OpenROAD Python Script: Merged and Verified Flow
#
# Based on user prompt requesting:
# Read netlist/tech files, set clock (40ns on clk_i), floorplan (50% util, 10um core-to-die),
# place pins (M8/M9), place macros (5um halo, try 5um separation), place std cells,
# global placement (30 iterations), detailed placement (0um displacement),
# CTS (BUF_X3, set RC 0.0435/0.0817), PDN construction (rings/straps/vias on specific layers/dims),
# dump PDN DEF, global/detailed routing, static IR drop (VDD net, M1 layer).
#
# This script merges logic from a provided Gemini draft and verifies against
# the detailed prompt, applying OpenROAD best practices.
###############################################################################

import openroad as ord
from openroad import Tech, Design, Timing
from pathlib import Path
import odb
import pdn
import grt # For GlobalRouter API
import drt # For TritonRoute API
import psm # For PDNSim API
import io_placer # For IOPlacer API
import mpl # For MacroPlacer API
import gpl # For RePlace API
import opendp # For OpenDP API
import cts # For TritonCts API

# Initialize the OpenROAD core environment
ord.init()
# Get the main database object - accessible after init
db = ord.get_db()

# --- Configuration ---
# Paths to technology, library, and design files
# !! IMPORTANT: Adjust these paths based on your file system structure and techlef/lib set !!
# Example paths assuming a typical OpenROAD flow setup:
# ./techlef_lib/Nangate45/Nangate45.lef
# ./techlef_lib/Nangate45/Nangate45_tech.lef
# ./techlef_lib/Nangate45/NangateOpenCellLibrary.lib
# ./design/gcd/gcd.v
techlef_dir = Path("../techlef_lib/Nangate45") # Directory containing tech LEF and cell LEFs
lib_dir = Path("../techlef_lib/Nangate45") # Directory containing Liberty files (.lib)
design_dir = Path("../design/gcd") # Directory containing the Verilog netlist

design_name = "gcd" # Name of the Verilog file without extension
design_top_module_name = "gcd" # Top module name in the Verilog
clock_port_name = "clk_i" # Name of the clock input port in the netlist
clock_period_ns = 40 # Clock period in nanoseconds

# Floorplan parameters
target_utilization = 0.50
core_margin_um = 10 # Spacing between core and die boundary

# Pin Placement parameters
io_place_hor_layer = "metal8"
io_place_ver_layer = "metal9"

# Macro Placement parameters
macro_halo_um = 5
# Note: Achieving exact macro-to-macro spacing (e.g., 5um) is complex with
# standard macro placement APIs. The halo helps keep other cells away.
# MacroPlacer itself uses internal mechanisms to optimize placement based on
# connectivity, area, and fence regions, but doesn't guarantee min separation
# between arbitrary macro pairs directly via a parameter.

# Placement parameters
global_placement_iterations = 30 # Interpreted from "global router iterations" in prompt
detailed_placement_max_disp_um_x = 0
detailed_placement_max_disp_um_y = 0

# CTS parameters
cts_buffer_cell = "BUF_X3"
clock_rc_resistance = 0.0435
clock_rc_capacitance = 0.0817
signal_rc_resistance = 0.0435
signal_rc_capacitance = 0.0817

# PDN parameters
vdd_net_name = "VDD"
vss_net_name = "VSS"

# Std Cell Grid & Rings (M7/M8 rings, M1/M4 straps)
ring_stdcell_width_um = 5
ring_stdcell_spacing_um = 5
strap_m1_width_um = 0.07
strap_m4_width_um = 1.2
strap_m4_spacing_um = 1.2
strap_m4_pitch_um = 6
strap_m7m8_width_um = 1.4
strap_m7m8_spacing_um = 1.4
strap_m7m8_pitch_um = 10.8

# Macro Grid & Rings (Conditional, on M5/M6)
# Used if macros exist in the design
ring_macro_width_um = 2
ring_macro_spacing_um = 2
strap_m5m6_width_um = 1.2
strap_m5m6_spacing_um = 1.2
strap_m5m6_pitch_um = 6

# Via Pitch for connects between parallel grids
via_pitch_um = 2

# Offset for all PDN shapes
pdn_offset_um = 0

# Output DEF file name
output_def_filename = "PDN.def"

# --- Setup and Read Inputs ---
print("--- Setting up OpenROAD and Reading Inputs ---")

# Create a Tech object and load technology LEF
print(f"Reading tech LEF from {techlef_dir}")
tech_lef_files = techlef_dir.glob("*_tech.lef")
tech_obj = Tech() # Create a Tech object linked to the current DB
for tech_lef in tech_lef_files:
    print(f"  Reading {tech_lef.name}")
    tech_obj.readLef(tech_lef.as_posix())

# Load cell LEF files
print(f"Reading cell LEFs from {techlef_dir}")
cell_lef_files = techlef_dir.glob("*.lef")
for cell_lef in cell_lef_files:
     # Avoid re-reading tech LEF if it's in the same directory
    if "_tech.lef" not in cell_lef.name:
        print(f"  Reading {cell_lef.name}")
        tech_obj.readLef(cell_lef.as_posix())

# Load Liberty files (.lib)
print(f"Reading Liberty files from {lib_dir}")
lib_files = lib_dir.glob("*.lib")
for lib_file in lib_files:
    print(f"  Reading {lib_file.name}")
    tech_obj.readLiberty(lib_file.as_posix())


# Create a Design object and read Verilog
print(f"Reading Verilog netlist: {design_name}.v from {design_dir}")
design = Design(tech_obj) # Create a Design object linked to the Tech object
verilog_path = design_dir / f"{design_name}.v"
if not verilog_path.exists():
    print(f"Error: Verilog file not found at {verilog_path}")
    exit()
design.readVerilog(verilog_path.as_posix())

# Link the design to connect sub-modules and libraries
print(f"Linking design with top module: {design_top_module_name}")
design.link(design_top_module_name)

# --- Constraints ---
print("\n--- Setting Constraints ---")

# Create clock constraint
print(f"Setting clock constraint: port={clock_port_name}, period={clock_period_ns} ns")
# Use evalTclString for standard OpenROAD Tcl commands
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}]")
design.evalTclString(f"set_propagated_clock [get_ports {clock_port_name}]")

# --- Floorplanning ---
print("\n--- Performing Floorplanning ---")

# Get the floorplan object
floorplan = design.getFloorplan()

# Find a standard cell site in the technology
# !! IMPORTANT: Replace with the actual site name from your tech LEF !!
site = tech.findSite("FreePDK45_38x28_10R_NP_162NW_34O")
if not site:
    print("Error: Standard cell site not found! Please check your tech LEF and site name.")
    # Attempt to find any CORE site as fallback
    for s in tech.getSites():
        if s.getType() == "CORE":
            site = s
            print(f"Warning: Using fallback CORE site: {site.getName()}")
            break
    if not site:
        print("Fatal Error: No CORE site found. Cannot proceed with floorplanning.")
        exit()

# Convert core margin to DBU
core_margin_dbu = design.micronToDBU(core_margin_um)

# Initialize floorplan (utilization, aspect ratio, core margins, site)
# Assuming aspect ratio 1.0 if not specified in prompt
aspect_ratio = 1.0
print(f"Initializing floorplan: utilization={target_utilization}, core_margin={core_margin_um} um, site={site.getName()}")
floorplan.initFloorplan(target_utilization, aspect_ratio,
    core_margin_dbu, core_margin_dbu, # Bottom/Top margins
    core_margin_dbu, core_margin_dbu, # Left/Right margins
    site)

# Create routing tracks based on the initialized floorplan
print("Creating routing tracks")
floorplan.makeTracks()

# --- Pin Placement ---
print("\n--- Performing Pin Placement ---")

# Get the IOPlacer object
io_placer_obj = design.getIOPlacer()
io_params = io_placer_obj.getParameters()

# Find target layers for IO placement
metal8 = db.getTech().findLayer(io_place_hor_layer)
metal9 = db.getTech().findLayer(io_place_ver_layer)

if metal8 and metal9:
    print(f"Adding horizontal pin layer: {metal8.getName()}")
    io_placer_obj.addHorLayer(metal8)
    print(f"Adding vertical pin layer: {metal9.getName()}")
    io_placer_obj.addVerLayer(metal9)
elif metal8:
     print(f"Warning: {io_place_ver_layer} not found. Only adding horizontal layer {metal8.getName()}.")
     io_placer_obj.addHorLayer(metal8)
elif metal9:
    print(f"Warning: {io_place_hor_layer} not found. Only adding vertical layer {metal9.getName()}.")
    io_placer_obj.addVerLayer(metal9)
else:
    print(f"Warning: Neither {io_place_hor_layer} nor {io_place_ver_layer} found. Attempting to use first two routing layers.")
    routing_layers = [layer for layer in db.getTech().getLayers() if layer.getType() == "ROUTING"]
    if len(routing_layers) >= 2:
         io_placer_obj.addHorLayer(routing_layers[0])
         io_placer_obj.addVerLayer(routing_layers[1])
         print(f"Using {routing_layers[0].getName()} (horizontal) and {routing_layers[1].getName()} (vertical) for IO placement.")
    else:
        print("Error: Could not find suitable routing layers for IO placement.")
        # Decide if this is a fatal error or if placement should continue without IOs
        # For this script, we'll continue but print a warning.

# Run IO placement (annealing mode is common)
print("Running IO placement")
io_placer_obj.runAnnealing(True) # True enables random mode

# --- Placement ---
print("\n--- Performing Placement ---")

# Get macro instances
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

# Get core area
block = design.getBlock()
core = block.getCoreArea()

# Conditional Macro Placement
if len(macros) > 0:
    print(f"Design contains {len(macros)} macros. Performing macro placement.")
    mpl_obj = design.getMacroPlacer()

    # Macro halo conversion to DBU
    macro_halo_width_dbu = design.micronToDBU(macro_halo_um)
    macro_halo_height_dbu = design.micronToDBU(macro_halo_um)

    # Define fence region for macro placement (typically core area)
    fence_lx = block.dbuToMicrons(core.xMin())
    fence_ly = block.dbuToMicrons(core.yMin())
    fence_ux = block.dbuToMicrons(core.xMax())
    fence_uy = block.dbuToMicrons(core.yMax())

    # Find Metal4 for pin snapping if needed (prompt specified macro PDN on M4, maybe pin snap?)
    metal4 = db.getTech().findLayer("metal4")
    snap_layer_idx = metal4.getRoutingLevel() if metal4 else -1

    # Run Macro Placement
    # The parameters below are typical and may need tuning.
    # Macro-to-macro spacing is influenced by halo and placer objective function,
    # not a strict minimum distance parameter in this API.
    mpl_obj.place(
        num_threads = 4,
        max_num_macro = len(macros),
        halo_width = macro_halo_um, # API takes microns
        halo_height = macro_halo_um, # API takes microns
        fence_lx = fence_lx,
        fence_ly = fence_ly,
        fence_ux = fence_ux,
        fence_uy = fence_uy,
        target_util = target_utilization, # Target utilization for std cells outside macros
        snap_layer = snap_layer_idx, # Optional: Snap macro pins to tracks on this layer
        report_directory = "" # Specify a directory for reports if needed
    )
else:
    print("No macros found in the design. Skipping macro placement.")


# Global Placement
print("\n--- Performing Global Placement ---")
gpl_obj = design.getReplace()

# Set Global Placement parameters based on prompt
gpl_obj.setTimingDrivenMode(False) # Prompt doesn't specify timing driven
gpl_obj.setRoutabilityDrivenMode(True)
gpl_obj.setUniformTargetDensityMode(True)
gpl_obj.setInitialPlaceMaxIter(global_placement_iterations)
print(f"Running global placement with {global_placement_iterations} initial iterations.")

# Run initial and Nesterov placement stages
gpl_obj.doInitialPlace(threads = 4)
gpl_obj.doNesterovPlace(threads = 4)

# Reset placer state after use
gpl_obj.reset()

# Initial Detailed Placement (before CTS)
print("\n--- Performing Initial Detailed Placement ---")
opendp_obj = design.getOpendp()

# Convert max displacement to DBU
max_disp_x_dbu = design.micronToDBU(detailed_placement_max_disp_um_x)
max_disp_y_dbu = design.micronToDBU(detailed_placement_max_disp_um_y)

print(f"Running detailed placement with max displacement: {detailed_placement_max_disp_um_x} um (x), {detailed_placement_max_disp_um_y} um (y)")

# Remove any existing filler cells before placement
opendp_obj.removeFillers()

# Perform detailed placement
opendp_obj.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False) # Params: max_disp_x, max_disp_y, cell_group, verbose

# --- Clock Tree Synthesis (CTS) ---
print("\n--- Performing Clock Tree Synthesis ---")
cts_obj = design.getTritonCts()

# Set RC values for clock and signal nets using TCL commands
print(f"Setting wire RC: Clock R={clock_rc_resistance}, C={clock_rc_capacitance}; Signal R={signal_rc_resistance}, C={signal_rc_capacitance}")
design.evalTclString(f"set_wire_rc -clock -resistance {clock_rc_resistance} -capacitance {clock_rc_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {signal_rc_resistance} -capacitance {signal_rc_capacitance}")

# Configure clock buffers
print(f"Setting clock buffer cell: {cts_buffer_cell}")
cts_obj.setBufferList(cts_buffer_cell)
cts_obj.setRootBuffer(cts_buffer_cell) # Use same buffer for root

# Run CTS
print("Running TritonCTS...")
cts_obj.runTritonCts()
print("CTS finished.")

# --- Post-CTS Placement Refinement ---
# Detailed placement and filler insertion are typically run again after CTS

# Post-CTS Detailed Placement
print("\n--- Performing Post-CTS Detailed Placement ---")
# Max displacement remains 0um
print(f"Running detailed placement with max displacement: {detailed_placement_max_disp_um_x} um (x), {detailed_placement_max_disp_um_y} um (y)")

# Remove any existing filler cells again
opendp_obj.removeFillers()

# Perform detailed placement
opendp_obj.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

# Insert Filler Cells
print("\n--- Inserting Filler Cells ---")
filler_masters = []
# Find CORE_SPACER cells in the loaded libraries
for lib in db.getLibs():
    for master in lib.getMasters():
        # Check if master type is CORE_SPACER (or similar, depends on library)
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)
        # Add other common filler types if known (e.g., CORE_GAP)
        # elif master.getType() == "CORE_GAP":
        #     filler_masters.append(master)

if len(filler_masters) == 0:
    print("Warning: No CORE_SPACER or CORE_GAP filler cells found in library! Cannot insert fillers.")
else:
    print(f"Found {len(filler_masters)} filler master types. Inserting fillers...")
    # Insert fillers into empty spaces in the core area
    opendp_obj.fillerPlacement(filler_masters = filler_masters,
                               prefix = "FILLCELL_", # Prefix for filler cell names
                               verbose = False)
    print("Filler cell insertion finished.")

# --- Power Delivery Network (PDN) Construction ---
print("\n--- Constructing Power Delivery Network ---")
pdngen_obj = design.getPdnGen()

# Ensure VDD/VSS nets are special and exist
vdd_net = design.getBlock().findNet(vdd_net_name)
vss_net = design.getBlock().findNet(vss_net_name)

if not vdd_net:
    print(f"Warning: VDD net '{vdd_net_name}' not found, creating it.")
    vdd_net = odb.dbNet_create(design.getBlock(), vdd_net_name)
    vdd_net.setSigType("POWER")
if not vss_net:
    print(f"Warning: VSS net '{vss_net_name}' not found, creating it.")
    vss_net = odb.dbNet_create(design.getBlock(), vss_net_name)
    vss_net.setSigType("GROUND")

vdd_net.setSpecial()
vss_net.setSpecial()

# Apply global connections for standard cells and macros
# This connects all power/ground pins matching patterns to the global VDD/VSS nets
print(f"Applying global connections for {vdd_net_name} and {vss_net_name}")
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = vdd_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = vss_net, do_connect = True)
# Add common additional patterns if needed (e.g., VDDPE, VDDCE, VSSE)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDPE$", net = vdd_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDCE$", net = vdd_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSSE$", net = vss_net, do_connect = True)

# Perform the global connections
design.getBlock().globalConnect()

# Set up the core power domain using the global nets
core_domain_name = "Core" # Default core domain name
print(f"Setting up core power domain '{core_domain_name}' with POWER='{vdd_net.getName()}' and GROUND='{vss_net.getName()}'")
# Using default arguments for switched_power and secondary nets
pdngen_obj.setCoreDomain(power = vdd_net, ground = vss_net)
core_domain = pdngen_obj.findDomain(core_domain_name)

if not core_domain:
    print(f"Error: Core power domain '{core_domain_name}' not found after setting up. Cannot proceed with PDN generation.")
    exit() # Fatal error

# Get required metal layers for PDN construction
m1 = db.getTech().findLayer("metal1")
m4 = db.getTech().findLayer("metal4")
m5 = db.getTech().findLayer("metal5")
m6 = db.getTech().findLayer("metal6")
m7 = db.getTech().findLayer("metal7")
m8 = db.getTech().findLayer("metal8")

required_layers_core = {"M1": m1, "M4": m4, "M7": m7, "M8": m8}
missing_core_layers = [name for name, layer in required_layers_core.items() if not layer]
if missing_core_layers:
    print(f"Error: Missing required metal layers for core PDN: {', '.join(missing_core_layers)}")
    # We will check before using each layer, but this is a heads-up.

required_layers_macro = {"M5": m5, "M6": m6}
missing_macro_layers = [name for name, layer in required_layers_macro.items() if not layer]
if len(macros) > 0 and missing_macro_layers:
     print(f"Warning: Missing required metal layers for macro PDN: {', '.join(missing_macro_layers)}")


# Convert PDN dimensions and offset to DBU
ring_stdcell_width_dbu = design.micronToDBU(ring_stdcell_width_um)
ring_stdcell_spacing_dbu = design.micronToDBU(ring_stdcell_spacing_um)
strap_m1_width_dbu = design.micronToDBU(strap_m1_width_um)
strap_m4_width_dbu = design.micronToDBU(strap_m4_width_um)
strap_m4_spacing_dbu = design.micronToDBU(strap_m4_spacing_um)
strap_m4_pitch_dbu = design.micronToDBU(strap_m4_pitch_um)
strap_m7m8_width_dbu = design.micronToDBU(strap_m7m8_width_um)
strap_m7m8_spacing_dbu = design.micronToDBU(strap_m7m8_spacing_um)
strap_m7m8_pitch_dbu = design.micronToDBU(strap_m7m8_pitch_um)
ring_macro_width_dbu = design.micronToDBU(ring_macro_width_um)
ring_macro_spacing_dbu = design.micronToDBU(ring_macro_spacing_um)
strap_m5m6_width_dbu = design.micronToDBU(strap_m5m6_width_um)
strap_m5m6_spacing_dbu = design.micronToDBU(strap_m5m6_spacing_um)
strap_m5m6_pitch_dbu = design.micronToDBU(strap_m5m6_pitch_um)
via_pitch_dbu = design.micronToDBU(via_pitch_um)
offset_dbu = design.micronToDBU(pdn_offset_um)

# Define offset lists for rings [left, bottom, right, top]
ring_offset = [offset_dbu] * 4

# Create the main core grid for standard cells
print("Creating core PDN grid...")
pdngen_obj.makeCoreGrid(domain = core_domain,
                        name = "stdcell_core_grid",
                        starts_with = pdn.GROUND) # Or pdn.POWER, doesn't strictly matter here

# Get the created grid object
stdcell_grid = pdngen_obj.findGrid("stdcell_core_grid")

if stdcell_grid and len(stdcell_grid) > 0:
    stdcell_grid_obj = stdcell_grid[0]

    # Create power rings around the core area on metal7 and metal8
    if m7 and m8:
        print(f"Creating core rings on {m7.getName()} and {m8.getName()} (width={ring_stdcell_width_um} um, spacing={ring_stdcell_spacing_um} um)")
        pdngen_obj.makeRing(grid = stdcell_grid_obj,
                            layer0 = m7, width0 = ring_stdcell_width_dbu, spacing0 = ring_stdcell_spacing_dbu,
                            layer1 = m8, width1 = ring_stdcell_width_dbu, spacing1 = ring_stdcell_spacing_dbu,
                            starts_with = pdn.GRID, # Connect rings to the core grid
                            offset = ring_offset,
                            extend = False, # Ring confined to core boundary
                            nets = []) # Use domain nets

    # Create horizontal followpin straps on metal1 for standard cells
    if m1:
        print(f"Creating horizontal followpin straps on {m1.getName()} (width={strap_m1_width_um} um)")
        pdngen_obj.makeFollowpin(grid = stdcell_grid_obj,
                                 layer = m1,
                                 width = strap_m1_width_dbu,
                                 extend = pdn.CORE) # Extend within the core area

    # Create vertical straps on metal4
    if m4:
        print(f"Creating vertical straps on {m4.getName()} (width={strap_m4_width_um} um, spacing={strap_m4_spacing_um} um, pitch={strap_m4_pitch_um} um)")
        pdngen_obj.makeStrap(grid = stdcell_grid_obj,
                             layer = m4,
                             width = strap_m4_width_dbu,
                             spacing = strap_m4_spacing_dbu,
                             pitch = strap_m4_pitch_dbu,
                             offset = offset_dbu,
                             starts_with = pdn.GRID,
                             extend = pdn.CORE, # Extend within core area
                             nets = [])

    # Create vertical straps on metal7 and metal8
    if m7:
         print(f"Creating vertical straps on {m7.getName()} (width={strap_m7m8_width_um} um, spacing={strap_m7m8_spacing_um} um, pitch={strap_m7m8_pitch_um} um)")
         pdngen_obj.makeStrap(grid = stdcell_grid_obj,
                              layer = m7,
                              width = strap_m7m8_width_dbu,
                              spacing = strap_m7m8_spacing_dbu,
                              pitch = strap_m7m8_pitch_dbu,
                              offset = offset_dbu,
                              starts_with = pdn.GRID,
                              extend = pdn.RINGS, # Extend to the rings
                              nets = [])
    if m8: # Note: M8 is horizontal layer by default in Nangate, check techlef for direction
         print(f"Creating horizontal straps on {m8.getName()} (width={strap_m7m8_width_um} um, spacing={strap_m7m8_spacing_um} um, pitch={strap_m7m8_pitch_um} um)")
         pdngen_obj.makeStrap(grid = stdcell_grid_obj,
                              layer = m8,
                              width = strap_m7m8_width_dbu,
                              spacing = strap_m7m8_spacing_dbu,
                              pitch = strap_m7m8_pitch_dbu,
                              offset = offset_dbu,
                              starts_with = pdn.GRID,
                              extend = pdn.RINGS, # Extend to the rings
                              nets = [])


    # Create via connections between layers in the standard cell grid
    print(f"Creating vias with pitch {via_pitch_um} um between parallel grid layers...")
    # Connections for core stdcell grid layers
    if m1 and m4:
         pdngen_obj.makeConnect(grid = stdcell_grid_obj, layer0 = m1, layer1 = m4,
                                cut_pitch_x = via_pitch_dbu, cut_pitch_y = via_pitch_dbu)
    if m4 and m7:
         pdngen_obj.makeConnect(grid = stdcell_grid_obj, layer0 = m4, layer1 = m7,
                                cut_pitch_x = via_pitch_dbu, cut_pitch_y = via_pitch_dbu)
    if m7 and m8: # Connect M7 straps to M8 straps/rings
         pdngen_obj.makeConnect(grid = stdcell_grid_obj, layer0 = m7, layer1 = m8,
                                cut_pitch_x = via_pitch_dbu, cut_pitch_y = via_pitch_dbu)

else:
    print("Error: Failed to create standard cell core grid.")


# Conditional Macro PDN Construction (if macros exist)
if len(macros) > 0:
    print(f"\nCreating PDN for {len(macros)} macros...")
    # Macro halo conversion to DBU list [left, bottom, right, top]
    macro_halo_dbu_list = [design.micronToDBU(macro_halo_um)] * 4

    if m5 and m6:
        for i, macro_inst in enumerate(macros):
            print(f"  Creating instance grid and PDN for macro: {macro_inst.getName()}")
            # Create a separate instance grid for each macro
            pdngen_obj.makeInstanceGrid(domain = core_domain, # Assume macros are in the core domain
                                        name = f"macro_grid_{i}",
                                        starts_with = pdn.GROUND, # Arbitrary start
                                        inst = macro_inst,
                                        halo = macro_halo_dbu_list, # Halo around the macro
                                        pg_pins_to_boundary = True) # Connect macro PG pins to grid boundary

            macro_grid = pdngen_obj.findGrid(f"macro_grid_{i}")
            if macro_grid and len(macro_grid) > 0:
                macro_grid_obj = macro_grid[0]

                # Create power ring around the macro instance on metal5 and metal6
                print(f"    Creating macro rings on {m5.getName()} and {m6.getName()} (width={ring_macro_width_um} um, spacing={ring_macro_spacing_um} um)")
                pdngen_obj.makeRing(grid = macro_grid_obj,
                                    layer0 = m5, width0 = ring_macro_width_dbu, spacing0 = ring_macro_spacing_dbu,
                                    layer1 = m6, width1 = ring_macro_width_dbu, spacing1 = ring_macro_spacing_dbu,
                                    starts_with = pdn.GRID, # Connect rings to the macro grid
                                    offset = ring_offset, # 0 offset from macro boundary
                                    extend = False, # Ring around macro instance
                                    nets = []) # Use domain nets

                # Create power straps on metal5 and metal6 for macro connections
                # Note: Assumes M5/M6 directions based on Nangate example (e.g. M5 Vert, M6 Horiz)
                if m5:
                    print(f"    Creating straps on {m5.getName()} (width={strap_m5m6_width_um} um, spacing={strap_m5m6_spacing_um} um, pitch={strap_m5m6_pitch_um} um)")
                    pdngen_obj.makeStrap(grid = macro_grid_obj,
                                         layer = m5,
                                         width = strap_m5m6_width_dbu,
                                         spacing = strap_m5m6_spacing_dbu,
                                         pitch = strap_m5m6_pitch_dbu,
                                         offset = offset_dbu,
                                         snap = True, # Snap to grid tracks/boundaries
                                         starts_with = pdn.GRID,
                                         extend = pdn.RINGS, # Extend to macro rings
                                         nets = [])
                if m6:
                    print(f"    Creating straps on {m6.getName()} (width={strap_m5m6_width_um} um, spacing={strap_m5m6_spacing_um} um, pitch={strap_m5m6_pitch_um} um)")
                    pdngen_obj.makeStrap(grid = macro_grid_obj,
                                         layer = m6,
                                         width = strap_m5m6_width_dbu,
                                         spacing = strap_m5m6_spacing_dbu,
                                         pitch = strap_m5m6_pitch_dbu,
                                         offset = offset_dbu,
                                         snap = True, # Snap to grid tracks/boundaries
                                         starts_with = pdn.GRID,
                                         extend = pdn.RINGS, # Extend to macro rings
                                         nets = [])

                # Create via connections between macro grid layers and adjacent core grid layers
                print(f"    Creating vias with pitch {via_pitch_um} um for macro grid...")
                # M4 (stdcell grid) to M5 (macro grid)
                if m4 and m5:
                     pdngen_obj.makeConnect(grid = macro_grid_obj, layer0 = m4, layer1 = m5,
                                            cut_pitch_x = via_pitch_dbu, cut_pitch_y = via_pitch_dbu)
                # M5 to M6 (macro grid layers)
                if m5 and m6:
                     pdngen_obj.makeConnect(grid = macro_grid_obj, layer0 = m5, layer1 = m6,
                                            cut_pitch_x = via_pitch_dbu, cut_pitch_y = via_pitch_dbu)
                # M6 (macro grid) to M7 (stdcell grid) - Connect macro PDN up to the core grid
                if m6 and m7:
                     pdngen_obj.makeConnect(grid = macro_grid_obj, layer0 = m6, layer1 = m7,
                                            cut_pitch_x = via_pitch_dbu, cut_pitch_y = via_pitch_dbu)
            else:
                 print(f"Warning: Failed to create instance grid for macro: {macro_inst.getName()}")
    else:
        print("Warning: Missing required metal layers M5 or M6 for macro PDN construction.")
else:
    print("No macros found, skipping macro PDN construction.")

# Verify and build the power delivery network
print("\nChecking and building PDN grids...")
pdngen_obj.checkSetup() # Check the PDN setup configuration
pdngen_obj.buildGrids(False) # Build the grids
pdngen_obj.writeToDb(True) # Write the generated PDN shapes to the database
print("PDN construction finished.")
pdngen_obj.resetShapes() # Clear temporary shapes used during generation

# Dump DEF file after PDN construction
print(f"Dumping DEF file: {output_def_filename}")
design.writeDef(output_def_filename)

# --- Routing ---
print("\n--- Performing Routing ---")

# Global Routing
print("Performing Global Routing...")
grt_obj = design.getGlobalRouter()

# Set routing layer ranges (assuming M1 is the lowest and M7 is high enough)
# Check if layers were found earlier
if m1 and m7:
    min_routing_layer = m1.getRoutingLevel()
    max_routing_layer = m7.getRoutingLevel()
    print(f"Setting routing layers from {m1.getName()} ({min_routing_layer}) to {m7.getName()} ({max_routing_layer})")
    grt_obj.setMinRoutingLayer(min_routing_layer)
    grt_obj.setMaxRoutingLayer(max_routing_layer)
    grt_obj.setMinLayerForClock(min_routing_layer)
    grt_obj.setMaxLayerForClock(max_routing_layer)
else:
    print("Warning: Could not find M1 or M7. Using default routing layer range for Global Router.")

grt_obj.setAdjustment(0.5) # Example parameter, controls congestion avoidance
grt_obj.setVerbose(True)
grt_obj.globalRoute(True) # True enables congestion-driven routing
print("Global Routing finished.")

# Detailed Routing
print("\nPerforming Detailed Routing...")
drter_obj = design.getTritonRoute()
drt_params = drt.ParamStruct() # Create parameter structure

# Configure detailed routing parameters
drt_params.enableViaGen = True # Enable via generation
drt_params.drouteEndIter = 1 # Number of detailed routing iterations (1 is common for initial run)
# Set routing layer names based on layers found earlier
if m1:
    drt_params.bottomRoutingLayer = m1.getName()
if m7:
    drt_params.topRoutingLayer = m7.getName()
drt_params.verbose = 1
drt_params.cleanPatches = True # Clean up routing patches
drt_params.doPa = True # Perform post-routing pin access optimization
drt_params.singleStepDR = False # Do not run detailed routing step-by-step

drter_obj.setParams(drt_params)

# Run detailed routing
drter_obj.main()
print("Detailed Routing finished.")


# --- Static IR Drop Analysis ---
print("\n--- Performing Static IR Drop Analysis ---")
psm_obj = design.getPDNSim()
timing_obj = Timing(design) # Need timing object to get analysis corner

# Find the VDD net
vdd_net_for_ir = design.getBlock().findNet(vdd_net_name)

if not vdd_net_for_ir:
    print(f"Error: VDD net '{vdd_net_name}' not found for IR drop analysis.")
elif not timing_obj.getCorners():
     print("Warning: No timing corners found. Cannot perform IR drop analysis.")
else:
    # Use the first timing corner found
    analysis_corner = timing_obj.getCorners()[0]
    print(f"Analyzing IR drop for net '{vdd_net_for_ir.getName()}' using timing corner '{analysis_corner.getName()}'")

    # Perform power grid analysis for the VDD net
    # The prompt asks for analysis "on M1 layer". The analyzePowerGrid function
    # analyzes the entire net. The results object (not directly returned to Python
    # in this API call) will contain voltage drop information for segments on M1.
    psm_obj.analyzePowerGrid(net = vdd_net_for_ir,
                             enable_em = False, # Disable electromigration
                             corner = analysis_corner,
                             use_prev_solution = False,
                             voltage_file = "", # Optional: Path to dump voltage map file
                             source_type = psm.GeneratedSourceType_FULL) # Analyze full grid based on standard cell/macro currents

    print(f"Static IR drop analysis performed on net '{vdd_net_for_ir.getName()}'. Results are available internally.")
    # To view results, you typically load the design in the OpenROAD GUI or process a dumped voltage file.

# Note: To get numerical results in Python, you might need to run a simulation
# and then query the results using the PSM API after analyzePowerGrid, or parse
# a dumped voltage file if generated. The current API call mainly triggers the analysis.


# --- End of Script ---
print("\n--- Script Finished ---")

# To save the final design database, you could use:
# design.writeDef("final_design.def")
# design.writeDb("final_design.db")