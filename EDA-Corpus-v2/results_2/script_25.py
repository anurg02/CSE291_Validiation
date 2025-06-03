#!/usr/bin/env python3

# OpenROAD Script: Consolidated Placement, CTS, and PDN Flow
#
# This script performs a typical digital design flow including:
# 1. Reading design inputs (LEF, LIB, Verilog)
# 2. Setting clock constraints
# 3. Floorplanning
# 4. Placing macros and standard cells (Global and Detailed Placement)
# 5. Setting Global Router iterations (as requested)
# 6. Performing Clock Tree Synthesis (CTS)
# 7. Constructing the Power Delivery Network (PDN)
# 8. Running static IR Drop analysis and extracting layer results
# 9. Writing out the final DEF file

import sys
import os
from pathlib import Path
from openroad import Tech, Design, Timing
import odb
import pdn
import psm
import router # Import the router module for global router settings

# --- User Configuration ---
# Set paths to your design and library files
# It's recommended to use absolute paths or paths relative to where the script is run.
# Example: Assuming your files are in a 'design' and 'libs' subdirectory
# design_dir = Path("./design")
# lib_dir = Path("./libs")
# lef_dir = Path("./libs")

# --- IMPORTANT: Replace these placeholders with your actual paths and names ---
design_dir = Path("/path/to/your/design") # e.g., Path("./design")
lib_dir = Path("/path/to/your/libs")     # e.g., Path("./libs")
lef_dir = Path("/path/to/your/lefs")     # e.g., Path("./libs")

design_top_module_name = "ADD_TOP_MODULE_NAME_HERE" # e.g., "my_design_top"
verilog_netlist_file = design_dir / "input_netlist.v" # e.g., design_dir / "my_design.v"

clock_port_name = "clk"
clock_period_ns = 20.0
clock_name = "core_clock"

# Clock buffer cell name from your library
clock_buffer_cell = "BUF_X2" # Ensure this cell exists in your LEF/LIB

# Power and Ground net names
vdd_net_name = "VDD" # Replace if different
vss_net_name = "VSS" # Replace if different

# Standard cell site name from your LEF files
std_cell_site_name = "core" # Replace with your actual standard cell site name

# --- Flow Start ---
print("--- Starting OpenROAD Python Flow ---")

# Initialize OpenROAD objects
tech = Tech()
design = Design(tech)

# 1. Read design inputs (LEF, LIB, Verilog)
print("--- Reading LEF/LIB/Verilog ---")

# Read all liberty (.lib) files
try:
    lib_files = sorted(lib_dir.glob("*.lib"))
    if not lib_files:
        print(f"Error: No .lib files found in {lib_dir}")
        sys.exit(1)
    for lib_file in lib_files:
        print(f"Reading liberty: {lib_file}")
        tech.readLiberty(lib_file.as_posix())
except Exception as e:
    print(f"Error reading liberty files from {lib_dir}: {e}")
    sys.exit(1)

# Read all LEF files (tech LEF first, then cell LEFs)
try:
    # Read tech LEF files first
    tech_lefs = sorted(lef_dir.glob("*.tech.lef"))
    if not tech_lefs:
        print("Warning: No *.tech.lef file found. Reading all *.lef files.")
        lefs = sorted(lef_dir.glob("*.lef"))
    else:
         print(f"Reading tech LEFs: {[f.name for f in tech_lefs]}")
         for tech_lef_file in tech_lefs:
            tech.readLef(tech_lef_file.as_posix())
         # Then read other LEFs
         lefs = sorted(lef_dir.glob("*.lef"))
         # Filter out tech LEFs already read
         lefs = [f for f in lefs if ".tech.lef" not in f.name]

    if not lefs and not tech_lefs:
         print(f"Error: No LEF files found in {lef_dir}")
         sys.exit(1)

    print(f"Reading cell/other LEFs: {[f.name for f in lefs]}")
    for lef_file in lefs:
        print(f"Reading cell LEF: {lef_file}")
        tech.readLef(lef_file.as_posix())

except Exception as e:
    print(f"Error reading LEF files from {lef_dir}: {e}")
    sys.exit(1)

# Create design and read Verilog netlist
if not verilog_netlist_file.exists():
    print(f"Error: Verilog netlist not found: {verilog_netlist_file}")
    sys.exit(1)

print(f"Reading Verilog netlist: {verilog_netlist_file}")
design.readVerilog(verilog_netlist_file.as_posix())

# Link the design to the loaded libraries
print(f"Linking design with top module: {design_top_module_name}")
try:
    design.link(design_top_module_name)
except Exception as e:
    print(f"Error linking design: {e}")
    print("Please check your top module name, LEF/LIB files, and netlist.")
    sys.exit(1)

print("--- Finished Reading Inputs ---")

# 2. Configure clock constraints
print("--- Setting Clock Constraints ---")
# Create clock on clk port and name it core_clock
print(f"Creating clock '{clock_name}' on port '{clock_port_name}' with period {clock_period_ns} ns")
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
# Propagate the clock signal for timing analysis
print(f"Setting propagated clock for '{clock_name}'")
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Set RC values for clock and signal wires for timing analysis (used by CTS and timing analysis)
wire_rc_resistance = 0.03574 # per unit length
wire_rc_capacitance = 0.07516 # per unit length
print(f"Setting clock wire RC: R={wire_rc_resistance}, C={wire_rc_capacitance}")
design.evalTclString(f"set_wire_rc -clock -resistance {wire_rc_resistance} -capacitance {wire_rc_capacitance}")
print(f"Setting signal wire RC: R={wire_rc_resistance}, C={wire_rc_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {wire_rc_resistance} -capacitance {wire_rc_capacitance}")

print("--- Finished Setting Clock Constraints ---")

# 3. Floorplanning
print("--- Performing Floorplanning ---")
floorplan = design.getFloorplan()

# Convert dimensions from microns to DBU (Database Units)
def um_to_dbu(design, um):
    return int(design.micronToDBU(um))

# Set die area: (0,0) to (60,50) um
die_ll_x_um, die_ll_y_um = 0.0, 0.0
die_ur_x_um, die_ur_y_um = 60.0, 50.0
die_ll_x_dbu = um_to_dbu(design, die_ll_x_um)
die_ll_y_dbu = um_to_dbu(design, die_ll_y_um)
die_ur_x_dbu = um_to_dbu(design, die_ur_x_um)
die_ur_y_dbu = um_to_dbu(design, die_ur_y_um)
die_area = odb.Rect(die_ll_x_dbu, die_ll_y_dbu, die_ur_x_dbu, die_ur_y_dbu)
print(f"Die Area: ({design.dbuToMicron(die_ll_x_dbu)},{design.dbuToMicron(die_ll_y_dbu)}) um to ({design.dbuToMicron(die_ur_x_dbu)},{design.dbuToMicron(die_ur_y_dbu)}) um")

# Set core area: (8,8) to (52,42) um
core_ll_x_um, core_ll_y_um = 8.0, 8.0
core_ur_x_um, core_ur_y_um = 52.0, 42.0
core_ll_x_dbu = um_to_dbu(design, core_ll_x_um)
core_ll_y_dbu = um_to_dbu(design, core_ll_y_um)
core_ur_x_dbu = um_to_dbu(design, core_ur_x_um)
core_ur_y_dbu = um_to_dbu(design, core_ur_y_um)
core_area = odb.Rect(core_ll_x_dbu, core_ll_y_dbu, core_ur_x_dbu, core_ur_y_dbu)
print(f"Core Area: ({design.dbuToMicron(core_ll_x_dbu)},{design.dbuToMicron(core_ll_y_dbu)}) um to ({design.dbuToMicron(core_ur_x_dbu)},{design.dbuToMicron(core_ur_y_dbu)}) um")


# Find a suitable standard cell site from the technology library
site = floorplan.findSite(std_cell_site_name)
if site is None:
    print(f"Warning: Specific site '{std_cell_site_name}' not found. Trying to find any standard cell site.")
    # Fallback: try to find any site that is not a PAD site
    db = design.getTech().getDB()
    for lib in db.getLibs():
        for s in lib.getSites():
            # Check if the site has a size (is a standard cell site) and is not a PAD or MACRO
            if s.getWidth() > 0 and s.getHeight() > 0 and s.getName() not in ["PAD", "MACRO"]:
                site = s
                print(f"Found fallback site: '{site.getName()}'")
                break
        if site:
            break

if site is None:
    print("Error: No standard cell site found in the loaded LEF files.")
    print("Please check your LEF files and the 'std_cell_site_name' configuration.")
    sys.exit(1)
else:
    print(f"Using standard cell site: '{site.getName()}' (Size: {design.dbuToMicron(site.getWidth())}x{design.dbuToMicron(site.getHeight())} um)")

# Initialize the floorplan with die area, core area, and site
print("Initializing floorplan...")
floorplan.initFloorplan(die_area, core_area, site)

# Make placement tracks based on the site and core area
print("Making placement tracks...")
floorplan.makeTracks()

print("--- Finished Floorplanning ---")

# 4. Placement
print("--- Performing Placement ---")

# Identify macro blocks
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
print(f"Found {len(macros)} macro instances.")

# Place macro blocks if present
if len(macros) > 0:
    print("Placing macros...")
    mpl = design.getMacroPlacer()

    # Macro fence region: (18,12) um to (43,42) um
    fence_lx_um = 18.0
    fence_ly_um = 12.0
    fence_ux_um = 43.0
    fence_uy_um = 42.0
    print(f"Setting macro fence region: ({fence_lx_um},{fence_ly_um}) um to ({fence_ux_um},{fence_uy_um}) um")

    # Halo region around each macro: 5 um
    macro_halo_width_um = 5.0
    macro_halo_height_um = 5.0
    print(f"Setting macro halo region: {macro_halo_width_um} um width, {macro_halo_height_um} um height")

    # Minimum distance between macros: 5 um
    # Note: The 'place' function parameters used here (RePlAce-macro) do not directly
    # guarantee minimum spacing between macros explicitly. Halo is set as requested,
    # which helps push standard cells and other objects away from the macro,
    # but doesn't strictly control macro-to-macro spacing. Achieving a precise
    # minimum spacing constraint between macros often requires density control,
    # manual placement, or more advanced tools/flows not covered by this basic API call.
    min_macro_spacing_um = 5.0 # As requested, but not directly controllable by this API

    # These parameters control the behavior of the macro placer algorithm (RePlAce-macro)
    # Adjust these parameters based on your needs and convergence.
    mpl.place(
        num_threads = os.cpu_count(), # Use available CPU threads
        max_num_macro = len(macros) if len(macros) > 0 else 1, # Max macros per group
        min_num_macro = 0, # Min macros per group
        max_num_inst = 0, # Max standard cells per group (0 means no limit/consideration)
        min_num_inst = 0, # Min standard cells per group
        tolerance = 0.1, # Placement tolerance
        max_num_level = 2, # Max hierarchy levels to consider
        coarsening_ratio = 10.0, # Coarsening ratio for hierarchical placement
        large_net_threshold = 50, # Threshold for large nets
        signature_net_threshold = 50, # Threshold for signature nets
        halo_width = macro_halo_width_um, # Halo width in microns
        halo_height = macro_halo_height_um, # Halo height in microns
        fence_lx = fence_lx_um, # Fence lower-left x in microns
        fence_ly = fence_ly_um, # Fence lower-left y in microns
        fence_ux = fence_ux_um, # Fence upper-right x in microns
        fence_uy = fence_uy_um, # Fence upper-right y in microns
        area_weight = 0.1, # Weight for area cost
        outline_weight = 100.0, # Weight for outline cost
        wirelength_weight = 100.0, # Weight for wirelength cost
        guidance_weight = 10.0, # Weight for guidance cost
        fence_weight = 10.0, # Weight for fence cost
        boundary_weight = 50.0, # Weight for boundary cost
        notch_weight = 10.0, # Weight for notch cost
        macro_blockage_weight = 10.0, # Weight for macro blockage cost
        pin_access_th = 0.0, # Pin access threshold
        target_util = 0.25, # Target utilization (example, adjust as needed)
        target_dead_space = 0.05, # Target dead space (example)
        min_ar = 0.33, # Minimum aspect ratio (example)
        # Snap macro pins to a routing layer (assuming metal4)
        # This helps macro pin connectivity during routing.
        # Find the routing level for the layer.
        snap_layer = None,
        # Add a check for metal4 existence before trying to find its level
        snap_metal_layer = design.getTech().getDB().getTech().findLayer("metal4"),
        # Use 'snap_metal_layer' object directly
        # Corrected syntax for if statement
        bus_planning_flag = False, # Disable bus planning
        report_directory = "" # No report directory
    )
    # Check if snap_metal_layer is valid and is a routing layer
    snap_layer = None
    snap_metal_layer_obj = design.getTech().getDB().getTech().findLayer("metal4")
    if snap_metal_layer_obj and snap_metal_layer_obj.getType() == "ROUTING":
         snap_layer = snap_metal_layer_obj.getRoutingLevel()
         print(f"Snapping macro pins to metal4 (level {snap_layer})")
    else:
         print("Warning: Could not find metal4 routing layer for macro pin snapping. Macro pins will not be snapped.")
         snap_layer = None # Ensure snap_layer is None if metal4 isn't suitable

    mpl.place(
        num_threads = os.cpu_count(),
        max_num_macro = len(macros) if len(macros) > 0 else 1,
        min_num_macro = 0,
        max_num_inst = 0,
        min_num_inst = 0,
        tolerance = 0.1,
        max_num_level = 2,
        coarsening_ratio = 10.0,
        large_net_threshold = 50,
        signature_net_threshold = 50,
        halo_width = macro_halo_width_um,
        halo_height = macro_halo_height_um,
        fence_lx = fence_lx_um,
        fence_ly = fence_ly_um,
        fence_ux = fence_ux_um,
        fence_uy = fence_uy_um,
        area_weight = 0.1,
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        pin_access_th = 0.0,
        target_util = 0.25,
        target_dead_space = 0.05,
        min_ar = 0.33,
        snap_layer = snap_layer, # Pass the determined snap layer level
        bus_planning_flag = False,
        report_directory = ""
    )
    print("Finished macro placement.")
else:
    print("No macros found. Skipping macro placement.")


# Configure and run global placement (Standard Cells)
print("Placing standard cells (Global Placement)...")
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Disable timing-driven mode (adjust if needed)
gpl.setRoutabilityDrivenMode(True) # Enable routability-driven mode
gpl.setUniformTargetDensityMode(True) # Use uniform target density

# Set placement iterations as requested (This is for Global Placement's Nesterov phase)
# The prompt specifically mentioned global *router* iterations (corrected below).
# Keeping global placement iterations reasonable for convergence.
gpl.setInitialPlaceMaxIter(10) # Max iterations for the coarse placement phase
# gpl.setNesterovPlaceMaxIter(5000) # Max iterations for the detailed Nesterov phase (default is large)
# gpl.setNesterovPlaceMinIter(100)  # Minimum iterations
gpl.setInitDensityPenalityFactor(0.05) # Initial density penalty factor

# Run initial global placement steps
# doInitialPlace: Coarse placement
gpl.doInitialPlace(threads = os.cpu_count())

# doNesterovPlace: Density-aware placement refinement
gpl.doNesterovPlace(threads = os.cpu_count())

print("Finished global placement.")

# Run initial detailed placement after global placement
print("Performing initial detailed placement...")
# Allow 0.5um x-displacement and 0.5um y-displacement
max_disp_x_um = 0.5
max_disp_y_um = 0.5
# Convert max displacement from microns to DBU
max_disp_x_dbu = um_to_dbu(design, max_disp_x_um)
max_disp_y_dbu = um_to_dbu(design, max_disp_y_um)

# Remove filler cells before detailed placement if they exist (important for clean placement)
# design.getOpendp().removeFillers() # Note: This might remove fillers placed during floorplan init

# Perform detailed placement
# Parameters: max_disp_x_dbu, max_disp_y_dbu, cell_list_str, check_placement_legality
design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Finished initial detailed placement.")

print("--- Finished Placement ---")

# 5. Setting Global Router Iterations (Added based on feedback)
print("--- Setting Global Router Iterations ---")
# The prompt requested setting iterations for the global router.
# While this script doesn't perform the global routing step, this configures
# the global router object for when a 'run_global_routing' call would occur.
gr = design.getGlobalRouter()
gr_iterations = 10
print(f"Setting Global Router iterations to {gr_iterations}")
gr.setIterations(gr_iterations)
# Note: Actual global routing would typically happen here or after CTS/buffering,
# using a command like design.evalTclString("run_global_routing").
print("Finished setting Global Router iterations.")
print("--- Finished Global Router Setting ---")

# 6. Clock Tree Synthesis (CTS)
print("--- Performing CTS ---")
cts = design.getTritonCts()

# Set clock net(s) to build the tree for
cts.setClockNets(clock_name)

# Set the available clock buffer cell list
# Ensure 'clock_buffer_cell' is defined and exists in LEF/LIB
if design.getBlock().findMaster(clock_buffer_cell) is None:
    print(f"Error: Clock buffer cell '{clock_buffer_cell}' not found in library.")
    print("Please check your LEF/LIB files and the 'clock_buffer_cell' configuration.")
    sys.exit(1)
cts.setBufferList(clock_buffer_cell)

# Set the root clock buffer cell (optional, defaults to first buffer in list)
cts.setRootBuffer(clock_buffer_cell)
# Set the sink clock buffer cell (optional, defaults to first buffer in list)
cts.setSinkBuffer(clock_buffer_cell)

# Run CTS
print(f"Running CTS with buffer '{clock_buffer_cell}'...")
cts.runTritonCts()
print("Finished CTS.")

# Run final detailed placement after CTS to legalize cells shifted by CTS
print("Performing final detailed placement after CTS...")
# Use the same displacement limits
design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Finished final detailed placement.")

print("--- Finished CTS ---")


# 7. Power Delivery Network (PDN) Construction
print("--- Constructing PDN ---")
pdngen = design.getPdnGen()

# Set up global power/ground connections
# Important: This connects instance power/ground pins to the global nets
print(f"Setting up global connections for {vdd_net_name} and {vss_net_name}")
# Find existing power and ground nets or create if needed
vdd_net = design.getBlock().findNet(vdd_net_name)
vss_net = design.getBlock().findNet(vss_net_name)

# Create VDD/VSS nets if they don't exist (should typically exist from netlist/LEF)
if vdd_net is None:
    print(f"Warning: Power net '{vdd_net_name}' not found, creating it.")
    vdd_net = odb.dbNet_create(design.getBlock(), vdd_net_name)
    vdd_net.setSigType("POWER")
if vss_net is None:
    print(f"Warning: Ground net '{vss_net_name}' not found, creating it.")
    vss_net = odb.dbNet_create(design.getBlock(), vss_net_name)
    vss_net.setSigType("GROUND")

# Mark power/ground nets as special nets - this is crucial for PDN generation
vdd_net.setSpecial()
vss_net.setSpecial()

# Connect standard cell VDD pins to VDD net and VSS pins to VSS net
# Assumes standard cells have pins named "VDD" and "VSS". Adjust pinPattern if needed.
# This is typically done with global connect
design.getBlock().addGlobalConnect(region = None,
    instPattern = "*", # Apply to all instances
    pinPattern = "^VDD$", # Pin name pattern
    net = vdd_net,
    do_connect = True)

design.getBlock().addGlobalConnect(region = None,
    instPattern = "*", # Apply to all instances
    pinPattern = "^VSS$", # Pin name pattern
    net = vss_net,
    do_connect = True)

# Apply the global connections
design.getBlock().globalConnect()
print("Applied global connections.")

# Configure power domains
# Set core power domain with primary power/ground nets
switched_power = None # No switched power domain in this design
secondary = list()  # No secondary power nets
# Correction: Changed 'swched_power' to 'switched_power' as per feedback
pdngen.setCoreDomain(power = vdd_net,
    switched_power = switched_power,
    ground = vss_net,
    secondary = secondary)
print("Set Core power domain.")

# Set via cut pitch to 0 μm (as requested)
pdn_cut_pitch_x_um = 0.0
pdn_cut_pitch_y_um = 0.0
pdn_cut_pitch_x_dbu = um_to_dbu(design, pdn_cut_pitch_x_um)
pdn_cut_pitch_y_dbu = um_to_dbu(design, pdn_cut_pitch_y_um)
print(f"Setting via cut pitch to ({pdn_cut_pitch_x_um},{pdn_cut_pitch_y_um}) um.")

# Set offset to 0 for all PDN structures (as requested)
pdn_offset_um = 0.0
pdn_offset_dbu = um_to_dbu(design, pdn_offset_um)
# makeRing and makeInstanceGrid offsets use a list [offset_lx, offset_ly, offset_ux, offset_uy]
pdn_offset_list_dbu = [pdn_offset_dbu] * 4
print(f"Setting all PDN offsets to {pdn_offset_um} um.")


# Get routing layers for PDN implementation
# Find layers by name and verify they are routing layers
def get_routing_layer(design, layer_name):
    layer = design.getTech().getDB().getTech().findLayer(layer_name)
    if layer is None:
        print(f"Error: Layer '{layer_name}' not found in LEF.")
        return None
    if layer.getType() != "ROUTING":
         print(f"Error: Layer '{layer_name}' is not a routing layer.")
         return None
    return layer

# Get all required layers upfront
m1 = get_routing_layer(design, "metal1")
m4 = get_routing_layer(design, "metal4")
m5 = get_routing_layer(design, "metal5")
m6 = get_routing_layer(design, "metal6")
m7 = get_routing_layer(design, "metal7")
m8 = get_routing_layer(design, "metal8")

required_layers = {"metal1": m1, "metal4": m4, "metal5": m5, "metal6": m6, "metal7": m7, "metal8": m8}
missing_layers = [name for name, obj in required_layers.items() if obj is None]

if missing_layers:
    print("PDN layer lookup failed. Missing required routing layers:")
    for layer_name in missing_layers:
        print(f"- {layer_name}")
    print("Please check your LEF files for these metal layers.")
    print("Available routing layers:")
    for layer in design.getTech().getDB().getTech().getLayers():
        if layer.getType() == "ROUTING":
            print(f"- {layer.getName()} (level {layer.getRoutingLevel()})")
    sys.exit(1)

print("Found all required metal layers for PDN.")


# Create core power grid structure
# This defines the grid structure but doesn't create shapes yet.
domains = pdngen.findDomain("Core") # Get the core domain object(s)
if not domains:
    print("Error: Core power domain not found. Check setCoreDomain call.")
    sys.exit(1)

core_domain = domains[0] # Assuming findDomain returns a list and we take the first one
print(f"Creating Core grid for domain '{core_domain.getName()}'...")
pdngen.makeCoreGrid(
    domain = core_domain,
    name = "core_grid",
    starts_with = pdn.GROUND,  # Start with ground net for pattern calculation
    pin_layers = [], # No specific pin layers defined for the core grid structure
    generate_obstructions = [], # No obstructions defined
    powercell = None, # No power cell
    powercontrol = None, # No power control net
    powercontrolnetwork = "STAR") # Default network type (STAR or BUS)

# Get the created core grid object
grid = pdngen.findGrid("core_grid")
if not grid:
    print("Error: Core grid not created. Check makeCoreGrid call.")
    sys.exit(1)

core_grid_obj = grid[0] # Assuming makeCoreGrid creates one grid object

# Add shapes (straps/rings) to the core grid
print("Adding shapes to Core grid...")

# M1: Standard cell connections (followpin)
# Width 0.07 um
m1_width_um = 0.07
print(f"Adding M1 followpin straps: width={m1_width_um} um")
pdngen.makeFollowpin(grid = core_grid_obj,
    layer = m1,
    width = um_to_dbu(design, m1_width_um),
    extend = pdn.CORE, # Extend to core boundary
    nets = []) # Use all nets in domain (VDD/VSS)

# M4: Standard cell straps
# Width 1.2 um, spacing 1.2 um, pitch 6 um
m4_width_um = 1.2
m4_spacing_um = 1.2
m4_pitch_um = 6.0
print(f"Adding M4 straps: width={m4_width_um} um, spacing={m4_spacing_um} um, pitch={m4_pitch_um} um")
pdngen.makeStrap(grid = core_grid_obj,
    layer = m4,
    width = um_to_dbu(design, m4_width_um),
    spacing = um_to_dbu(design, m4_spacing_um),
    pitch = um_to_dbu(design, m4_pitch_um),
    offset = pdn_offset_dbu, # Offset from core boundary
    number_of_straps = 0,  # Auto-calculate number of straps based on pitch/offset/area
    snap = False, # Snap to grid/pitch is handled by pitch value
    starts_with = pdn.GRID, # Align pattern with grid start
    extend = pdn.CORE, # Extend straps to core boundary
    nets = []) # Use all nets in domain

# M7: Straps
# Width 1.4 um, spacing 1.4 um, pitch 10.8 um
m7_strap_width_um = 1.4
m7_strap_spacing_um = 1.4
m7_strap_pitch_um = 10.8
print(f"Adding M7 straps: width={m7_strap_width_um} um, spacing={m7_strap_spacing_um} um, pitch={m7_strap_pitch_um} um")
pdngen.makeStrap(grid = core_grid_obj,
    layer = m7,
    width = um_to_dbu(design, m7_strap_width_um),
    spacing = um_to_dbu(design, m7_strap_spacing_um),
    pitch = um_to_dbu(design, m7_strap_pitch_um),
    offset = pdn_offset_dbu,
    number_of_straps = 0,
    snap = False,
    starts_with = pdn.GRID,
    extend = pdn.CORE, # Extend straps to core boundary
    nets = [])

# M8: Straps
# Width 1.4 um, spacing 1.4 um, pitch 10.8 um (using same as M7 straps as M8 rings are 2um)
# The prompt requested M8 straps with width 1.4, spacing 1.4, pitch 10.8.
m8_strap_width_um = 1.4
m8_strap_spacing_um = 1.4
m8_strap_pitch_um = 10.8
print(f"Adding M8 straps: width={m8_strap_width_um} um, spacing={m8_strap_spacing_um} um, pitch={m8_strap_pitch_um} um")
pdngen.makeStrap(grid = core_grid_obj,
    layer = m8,
    width = um_to_dbu(design, m8_strap_width_um),
    spacing = um_to_dbu(design, m8_strap_spacing_um),
    pitch = um_to_dbu(design, m8_strap_pitch_um),
    offset = pdn_offset_dbu,
    number_of_straps = 0,
    snap = False,
    starts_with = pdn.GRID,
    extend = pdn.BOUNDARY, # Extend M8 straps to die boundary
    nets = [])


# M7: Power rings around core boundary
# Width 2 um, spacing 2 um
m7_ring_width_um = 2.0
m7_ring_spacing_um = 2.0
print(f"Adding M7 rings around core: width={m7_ring_width_um} um, spacing={m7_ring_spacing_um} um")
pdngen.makeRing(grid = core_grid_obj,
    layer0 = m7, width0 = um_to_dbu(design, m7_ring_width_um), spacing0 = um_to_dbu(design, m7_ring_spacing_um),
    layer1 = m7, width1 = um_to_dbu(design, m7_ring_width_um), spacing1 = um_to_dbu(design, m7_ring_spacing_um), # Same layer for both sides of ring
    starts_with = pdn.GRID, # Align pattern with grid start
    offset = pdn_offset_list_dbu, # Offset from core boundary [l,b,r,t]
    pad_offset = pdn_offset_list_dbu, # Pad offset (same as main offset)
    extend = False, # Do not extend the ring
    pad_pin_layers = [], # No pad pin layers for core ring
    nets = [], # Use all nets in domain
    allow_out_of_die = True) # Allow rings to go slightly out if needed for alignment

# M8: Power rings around core boundary
# Width 2 um, spacing 2 um
m8_ring_width_um = 2.0
m8_ring_spacing_um = 2.0
print(f"Adding M8 rings around core: width={m8_ring_width_um} um, spacing={m8_ring_spacing_um} um")
pdngen.makeRing(grid = core_grid_obj,
    layer0 = m8, width0 = um_to_dbu(design, m8_ring_width_um), spacing0 = um_to_dbu(design, m8_ring_spacing_um),
    layer1 = m8, width1 = um_to_dbu(design, m8_ring_width_um), spacing1 = um_to_dbu(design, m8_ring_spacing_um), # Same layer
    starts_with = pdn.GRID,
    offset = pdn_offset_list_dbu,
    pad_offset = pdn_offset_list_dbu,
    extend = False,
    pad_pin_layers = [],
    nets = [],
    allow_out_of_die = True)

# Create via connections between standard cell grid layers
print("Adding via connections for Core grid...")
# Connect M1 to M4
pdngen.makeConnect(grid = core_grid_obj,
    layer0 = m1, layer1 = m4,
    cut_pitch_x = pdn_cut_pitch_x_dbu, cut_pitch_y = pdn_cut_pitch_y_dbu, # Set via pitch to 0
    vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
print("Added M1-M4 vias.")

# Connect M4 to M7
pdngen.makeConnect(grid = core_grid_obj,
    layer0 = m4, layer1 = m7,
    cut_pitch_x = pdn_cut_pitch_x_dbu, cut_pitch_y = pdn_cut_pitch_y_dbu,
    vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
print("Added M4-M7 vias.")

# Connect M7 to M8 (for straps and rings)
pdngen.makeConnect(grid = core_grid_obj,
    layer0 = m7, layer1 = m8,
    cut_pitch_x = pdn_cut_pitch_x_dbu, cut_pitch_y = pdn_cut_pitch_y_dbu,
    vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
print("Added M7-M8 vias.")


# Create power grid for macro blocks (Instance Grids) if macros exist
if len(macros) > 0:
    print("Creating Instance grids for macros...")
    # Use the same halo defined for macro placement
    macro_pdn_halo_um = [macro_halo_width_um, macro_halo_width_um, macro_halo_height_um, macro_halo_height_um]
    macro_pdn_halo_dbu = [um_to_dbu(design, h) for h in macro_pdn_halo_um]
    print(f"Using macro halo {macro_pdn_halo_um} um for instance grids.")

    # Macro PDN on M5 and M6
    m5_width_um = 1.2
    m5_spacing_um = 1.2
    m5_pitch_um = 6.0
    m6_width_um = 1.2
    m6_spacing_um = 1.2
    m6_pitch_um = 6.0
    m5_ring_width_um = 1.5
    m5_ring_spacing_um = 1.5
    m6_ring_width_um = 1.5
    m6_ring_spacing_um = 1.5

    for i, macro_inst in enumerate(macros):
        print(f"Processing macro instance: {macro_inst.getName()}")
        # Create a separate instance grid structure for each macro
        # Macros are usually in the core domain
        pdngen.makeInstanceGrid(
            domain = core_domain, # Assign to the core domain
            name = f"macro_grid_{macro_inst.getName()}", # Unique name per macro
            starts_with = pdn.GROUND, # Start with ground net
            inst = macro_inst, # Target instance
            halo = macro_pdn_halo_dbu, # Halo around macro instance
            pg_pins_to_boundary = True,  # Connect macro power/ground pins to grid boundary
            default_grid = False, # Not the default grid
            generate_obstructions = [], # No obstructions
            is_bump = False) # Not a bump grid

        # Get the created instance grid object
        macro_grid = pdngen.findGrid(f"macro_grid_{macro_inst.getName()}")
        if not macro_grid:
             print(f"Warning: Instance grid for macro {macro_inst.getName()} not created.")
             continue # Skip adding shapes/vias if grid wasn't created

        macro_grid_obj = macro_grid[0] # Assuming makeInstanceGrid creates one grid object

        # Add shapes (straps/rings) to the instance grid
        # M5: Straps
        # Width 1.2 um, spacing 1.2 um, pitch 6 um
        print(f"Adding M5 straps for {macro_inst.getName()}: width={m5_width_um} um, spacing={m5_spacing_um} um, pitch={m5_pitch_um} um")
        pdngen.makeStrap(grid = macro_grid_obj,
            layer = m5,
            width = um_to_dbu(design, m5_width_um),
            spacing = um_to_dbu(design, m5_spacing_um),
            pitch = um_to_dbu(design, m5_pitch_um),
            offset = pdn_offset_dbu,
            number_of_straps = 0,
            snap = True,  # Snap to grid for macro straps
            starts_with = pdn.GRID,
            extend = pdn.CORE, # Extend straps within the instance grid region
            nets = [])

        # M6: Straps
        # Width 1.2 um, spacing 1.2 um, pitch 6 um
        print(f"Adding M6 straps for {macro_inst.getName()}: width={m6_width_um} um, spacing={m6_spacing_um} um, pitch={m6_pitch_um} um")
        pdngen.makeStrap(grid = macro_grid_obj,
            layer = m6,
            width = um_to_dbu(design, m6_width_um),
            spacing = um_to_dbu(design, m6_spacing_um),
            pitch = um_to_dbu(design, m6_pitch_um),
            offset = pdn_offset_dbu,
            number_of_straps = 0,
            snap = True,
            starts_with = pdn.GRID,
            extend = pdn.CORE, # Extend straps within the instance grid region
            nets = [])

        # M5: Rings around macro instance boundary
        # Width 1.5 um, spacing 1.5 um
        print(f"Adding M5 rings for {macro_inst.getName()}: width={m5_ring_width_um} um, spacing={m5_ring_spacing_um} um")
        pdngen.makeRing(grid = macro_grid_obj,
            layer0 = m5, width0 = um_to_dbu(design, m5_ring_width_um), spacing0 = um_to_dbu(design, m5_ring_spacing_um),
            layer1 = m5, width1 = um_to_dbu(design, m5_ring_width_um), spacing1 = um_to_dbu(design, m5_ring_spacing_um),
            starts_with = pdn.GRID,
            offset = pdn_offset_list_dbu, # Offset from macro instance boundary [l,b,r,t]
            pad_offset = pdn_offset_list_dbu, # Pad offset (same as main offset)
            extend = False,
            pad_pin_layers = [], # No pad pin layers for macro ring
            nets = [], # Use all nets in domain
            allow_out_of_die = True) # Allow rings to go slightly out if needed for alignment

        # M6: Rings around macro instance boundary
        # Width 1.5 um, spacing 1.5 um
        print(f"Adding M6 rings for {macro_inst.getName()}: width={m6_ring_width_um} um, spacing={m6_ring_spacing_um} um")
        pdngen.makeRing(grid = macro_grid_obj,
            layer0 = m6, width0 = um_to_dbu(design, m6_ring_width_um), spacing0 = um_to_dbu(design, m6_ring_spacing_um),
            layer1 = m6, width1 = um_to_dbu(design, m6_ring_width_um), spacing1 = um_to_dbu(design, m6_ring_spacing_um),
            starts_with = pdn.GRID,
            offset = pdn_offset_list_dbu, # Offset from macro instance boundary
            pad_offset = pdn_offset_list_dbu,
            extend = False,
            pad_pin_layers = [],
            nets = [],
            allow_out_of_die = True)

        # Create via connections for macro instance grid and connections to core grid
        print(f"Adding via connections for {macro_inst.getName()} instance grid...")
        # Connect M4 (from core grid) to M5 (macro grid)
        # Note: This creates vias where the macro grid overlaps with the core grid layers
        pdngen.makeConnect(grid = macro_grid_obj,
            layer0 = m4, layer1 = m5,
            cut_pitch_x = pdn_cut_pitch_x_dbu, cut_pitch_y = pdn_cut_pitch_y_dbu,
            vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
        print(f"Added M4-M5 vias for {macro_inst.getName()}.")

        # Connect M5 to M6 (macro grid layers)
        pdngen.makeConnect(grid = macro_grid_obj,
            layer0 = m5, layer1 = m6,
            cut_pitch_x = pdn_cut_pitch_x_dbu, cut_pitch_y = pdn_cut_pitch_y_dbu,
            vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
        print(f"Added M5-M6 vias for {macro_inst.getName()}.")

        # Connect M6 (macro grid) to M7 (core grid)
        pdngen.makeConnect(grid = macro_grid_obj,
            layer0 = m6, layer1 = m7,
            cut_pitch_x = pdn_cut_pitch_x_dbu, cut_pitch_y = pdn_cut_pitch_y_dbu,
            vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
        print(f"Added M6-M7 vias for {macro_inst.getName()}.")

else:
    print("No macros found. Skipping macro instance grid creation.")


# Generate the final power delivery network shapes
print("Building PDN grids...")
pdngen.checkSetup()  # Verify PDN configuration before building
pdngen.buildGrids(False)  # Build the power grid structures (creates shapes in memory)

# Write power grid shapes to the design database
# This makes the PDN shapes part of the design database (odb)
print("Writing PDN shapes to database...")
pdngen.writeToDb(True)
# pdngen.resetShapes()  # Reset temporary shapes used during build (optional)
print("Finished writing PDN shapes.")

print("--- Finished PDN Construction ---")


# 8. Static IR Drop Analysis
print("--- Performing Static IR Drop Analysis ---")
psm_obj = design.getPDNSim()

# Get current timing corner (assuming one corner exists)
# Static IR drop needs a loaded timing analysis corner to get current sources.
# Ensure SPEF/DSPF is loaded before running IR drop for accurate results.
# The prompt doesn't mention loading parasitics or activity, so analysis
# might run without them or use default estimates. For real analysis, load
# parasitics and activity (e.g., from a simulation output) first.
timing = Timing(design)
timing_corner = timing.getCorners()[0] if timing.getCorners() else None

if timing_corner:
    print(f"Using timing corner: {timing_corner.getName()}")
    # Define source types for analysis.
    # psm.GeneratedSourceType_FULL is often used when current sources are loaded
    # (e.g., from a power analysis tool output).
    # Without loaded current sources, results might be based on average cell power or estimates.
    # For a simple functional check, this source type might still work depending on PSM setup.
    # It's generally recommended to load current sources from a simulation/activity file for accuracy.
    source_types = [psm.GeneratedSourceType_FULL] # Using FULL type as an example

    # Analyze VDD power grid IR drop
    # The analysis is performed on the whole VDD net grid.
    # Results (voltage/current maps) are stored internally and can be accessed per layer
    # after the analysis completes.
    ir_drop_voltage_file = "ir_drop_VDD.rpt"
    ir_drop_error_file = "psm_errors.log"

    print(f"Running static IR drop analysis on net: {vdd_net_name}")
    print(f"Output voltage report file: {ir_drop_voltage_file}")
    print(f"Output error log file: {ir_drop_error_file}")

    try:
        # Set the current sources for the analysis if not already loaded
        # (e.g., from a loaded SPEF/DSPF and power analysis data)
        # This step is crucial for meaningful IR drop results.
        # If no activity data or SPEF/DSPF is loaded, this might use default values.
        psm_obj.addCurrentSources(
            insts=design.getBlock().getInsts(),
            src_type=psm.SourceType_GATE, # Apply sources to gate instances
            src_generated_type=source_types[0],
            nets=[vdd_net] # Apply sources related to the VDD net
        )
        print("Added current sources (using default/loaded values).")

        psm_obj.analyzePowerGrid(
            net = vdd_net, # Analyze the VDD net grid
            enable_em = False, # Disable electromigration analysis (not requested)
            corner = timing_corner,
            use_prev_solution = False, # Do not use previous solution
            em_file = "", # No EM report file
            error_file = ir_drop_error_file, # Log errors
            voltage_source_file = "", # No separate voltage source file
            voltage_file = ir_drop_voltage_file # Output voltage report (summarized)
            # source_type is configured via addCurrentSources, not analyzePowerGrid
        )
        print("Static IR drop analysis completed.")
        print(f"Summary voltage report is in {ir_drop_voltage_file}. Details can be viewed in the GUI.")


        # --- Extract and report IR Drop on M1 layer (Added based on feedback) ---
        print(f"Extracting IR drop results for layer: {m1.getName()}")
        if m1: # Check if M1 layer object was successfully retrieved earlier
            ir_drop_map = psm_obj.getIRDropMap(vdd_net) # Get the analysis map for the VDD net
            if ir_drop_map:
                min_voltage_m1 = float('inf')
                max_voltage_m1 = float('-inf')
                point_count_m1 = 0

                # The map contains points and their corresponding voltage values
                # Iterate through the points and filter by layer level
                m1_level = m1.getRoutingLevel()
                for point_data in ir_drop_map:
                    layer_level = point_data.getLayerLevel()
                    voltage = point_data.getVoltage()
                    # Check if the point is on the M1 layer
                    if layer_level == m1_level:
                        min_voltage_m1 = min(min_voltage_m1, voltage)
                        max_voltage_m1 = max(max_voltage_m1, voltage)
                        point_count_m1 += 1

                if point_count_m1 > 0:
                    print(f"IR Drop Summary for {m1.getName()} ({vdd_net_name} net):")
                    print(f"  Points analyzed on M1: {point_count_m1}")
                    print(f"  Minimum Voltage: {min_voltage_m1:.6f} V")
                    print(f"  Maximum Voltage: {max_voltage_m1:.6f} V")
                    # Calculate IR drop relative to the maximum voltage found on M1
                    # This is a simple IR drop estimation for this layer.
                    ir_drop_m1_est = max_voltage_m1 - min_voltage_m1
                    print(f"  Estimated IR Drop (Max - Min on M1): {ir_drop_m1_est:.6f} V")
                else:
                    print(f"No analysis points found on layer {m1.getName()} for net {vdd_net_name}.")
            else:
                 print(f"Warning: Could not retrieve IR drop map for net {vdd_net_name}. Analysis might have failed or produced no map.")
        else:
            print("Warning: M1 layer object not available for extracting results.")

    except Exception as e:
         print(f"Error during static IR drop analysis: {e}")
         print("Note: Static IR Drop analysis requires current source information, typically loaded from activity files or power analysis tools.")
         print("Ensure timing is setup, parasitics (SPEF/DSPF) and current sources are available if results seem unexpected.")

else:
    print("Warning: No timing corner found for IR drop analysis. Skipping static IR drop.")
    print("Load timing information (e.g., SDC) and parasitics (e.g., SPEF/DSPF) before running IR drop.")


print("--- Finished Static IR Drop Analysis ---")

# 9. Write outputs
print("--- Writing Outputs ---")

# Write the final DEF file with the floorplan, placement, CTS, and PDN
def_output_file = "PDN.def"
print(f"Writing final DEF file: {def_output_file}")
design.writeDef(def_output_file)
print("Finished writing DEF.")


# Optionally save other outputs like Verilog or ODB database
# design.evalTclString("write_verilog final.v") # Uncomment to save Verilog netlist after modifications
# design.writeDb("final.odb") # Uncomment to save the ODB database (contains everything)

print("--- OpenROAD Python Flow Completed ---")