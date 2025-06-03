import odb
import pdn
import drt
import openroad as ord
import math

# Standard OpenROAD startup code assumed before this script runs.
# 'design' object is available and design is loaded (netlist, LEF, etc.).
# Libraries, technology data, and the synthesized netlist should be loaded
# before executing this script.

# Example assumed setup (replace with actual loading in your flow):
# ord.read_libs(["./libraries/liberty/my_lib.lib"])
# ord.read_lef(["./libraries/lef/my_tech.lef", "./libraries/lef/my_macros.lef"])
# ord.read_def("./results/synthesis/my_design.def") # Or read verilog and link design

# Check if the design block is loaded
db = ord.get_db()
design = ord.get_design()

if design is None or design.getBlock() is None:
    print("Error: Design or block not loaded. Please ensure LEF, libraries, and netlist are loaded before running this script.")
    exit(1)

tech = db.getTech()
block = design.getBlock()

print("Starting OpenROAD Python Place and Route flow...")

# 1. Set Clock / RC
print("\n[INFO] Setting clock and wire RC values...")
clock_period_ns = 20
clock_period_ps = clock_period_ns * 1000 # Clock period in picoseconds
clock_port_name = "clk_i"
clock_name = "core_clock"

# Create clock signal using TCL command
# Tcl commands are executed via evalTclString
design.evalTclString(f"create_clock -period {clock_period_ps} [get_ports {clock_port_name}] -name {clock_name}")
# Propagate the clock signal
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Set RC values for clock and signal nets
resistance_per_unit = 0.0435
capacitance_per_unit = 0.0817
# Use evalTclString to execute TCL commands for setting wire RC
design.evalTclString(f"set_wire_rc -clock -resistance {resistance_per_unit} -capacitance {capacitance_per_unit}")
design.evalTclString(f"set_wire_rc -signal -resistance {resistance_per_unit} -capacitance {capacitance_per_unit}")
print("[INFO] Clock and wire RC values set.")

# 2. Floorplanning
print("\n[INFO] Performing floorplanning...")
# Calculate total standard cell area to inform utilization-based floorplanning
total_std_cell_area = 0
for inst in block.getInsts():
    master = inst.getMaster()
    # Check if the instance is a standard cell (not a block/macro)
    if master and not master.isBlock():
        total_std_cell_area += master.getArea()

# Set floorplan parameters from prompt
target_utilization = 0.5
core_to_die_spacing_um = 14 # Spacing between core and die boundary
core_to_die_spacing_dbu = design.micronToDBU(core_to_die_spacing_um)

# Core margin (spacing from core boundary to row boundary), usually 0 or site height multiple
# Prompt specifies 0um for other settings not mentioned, so core margin is 0.
core_margin_dbu = design.micronToDBU(0)

floorplan = design.getFloorplan()

# Find a site definition from the design's rows or libraries to use for floorplanning grid
site = None
rows = block.getRows()
if rows:
    # Use site from existing rows if design already has them
    site = rows[0].getSite()
    site_name = site.getName()
    print(f"[INFO] Using site '{site_name}' found in existing design rows.")
else:
    # Fallback: try to find a CORE_SITE in the libraries
    print("[INFO] No rows found in the design. Attempting to find a CORE_SITE in libraries for floorplanning.")
    site = None
    for lib in db.getLibs():
        for lib_site in lib.getSites():
            if lib_site.getType() == "CORE_SITE":
                site = lib_site
                break
        if site: break

    if site:
        site_name = site.getName()
        print(f"[INFO] Using site '{site_name}' found in library '{site.getLib().getName()}' for floorplanning.")
    else:
        print("[ERROR] No CORE_SITE found in libraries either. Cannot perform floorplanning.")
        exit(1) # Exit if no site is found

# Initialize floorplan
# Arguments: target_utilization, core_margin_dbu (all 4 sides), die_margin_dbu (all 4 sides), site_name
try:
    floorplan.initFloorplan(target_utilization, core_margin_dbu, core_to_die_spacing_dbu, site_name)
except Exception as e:
    print(f"[ERROR] Failed to initialize floorplan: {e}")
    exit(1)

# Make placement tracks based on the site definition and floorplan
try:
    floorplan.makeTracks()
except Exception as e:
    print(f"[ERROR] Failed to make tracks: {e}")
    # Non-fatal for floorplan itself, but needed for placement. Continue but warn.
    print("[WARNING] Could not create placement tracks. Placement tools may fail.")


# Get the core and die areas after floorplanning
core_area = block.getCoreArea()
die_area = block.getDieArea()
print(f"[INFO] Floorplan complete.")
print(f"  Die Area: ({block.dbuToMicrons(die_area.xMin())}um, {block.dbuToMicrons(die_area.yMin())}um) to ({block.dbuToMicrons(die_area.xMax())}um, {block.dbuToMicrons(die_area.yMax())}um)")
print(f"  Core Area: ({block.dbuToMicrons(core_area.xMin())}um, {block.dbuToMicrons(core_area.yMin())}um) to ({block.dbuToMicrons(core_area.xMax())}um, {block.dbuToMicrons(core_area.yMax())}um)")


# 3. IO Placement
print("\n[INFO] Performing IO placement...")
iop = design.getIOPlacer()
params = iop.getParameters()

# Set IO placement parameters - using 0um distance/avoidance as per '0um for other settings'
params.setMinDistanceInTracks(False)
params.setMinDistance(design.micronToDBU(0)) # 0um min distance
params.setCornerAvoidance(design.micronToDBU(0)) # 0um corner avoidance

# Get metal layers for IO placement (M8, M9)
m8 = tech.findLayer("metal8")
m9 = tech.findLayer("metal9")

# Helper function to get layer routing direction heuristic
def get_layer_routing_direction_heuristic(layer):
    "Attempt to determine layer routing direction using heuristic."
    if not layer: return "unknown"
    layer_name = layer.getName().lower()
    # Check common naming conventions (e.g., M1, M3, M5, M7, M9 are H; M2, M4, M6, M8 are V)
    # Check odd/even routing levels (Odd H, Even V is a common pattern)
    level = layer.getRoutingLevel()
    if level > 0: # Level 0 is usually poly or diffusion, not for routing grids
         if level % 2 != 0: # Odd level
             return "horizontal"
         else: # Even level
             return "vertical"
    # Fallback check based on name if level 0 or unknown
    if any(x in layer_name for x in ["hor", "_h"]) or any(layer_name.endswith(str(i)) for i in [1, 3, 5, 7, 9]):
         return "horizontal"
    if any(x in layer_name for x in ["ver", "_v"]) or any(layer_name.endswith(str(i)) for i in [2, 4, 6, 8]):
         return "vertical"
    print(f"[WARNING] Could not reliably determine routing direction for layer {layer_name} (level {level}). Assuming default.")
    return "unknown" # Cannot determine


m8_direction = get_layer_routing_direction_heuristic(m8)
m9_direction = get_layer_routing_direction_heuristic(m9)

# Place pins on M8 and M9. Direction matters for IO placer.
# The addHorLayer adds a layer for horizontal I/O pins (which use vertical vias/wires).
# The addVerLayer adds a layer for vertical I/O pins (which use horizontal vias/wires).
# So, a Vertical routing layer (like M8 if even level) is used with `addHorLayer`.
# A Horizontal routing layer (like M9 if odd level) is used with `addVerLayer`.

print(f"[INFO] M8 routing direction heuristic: {m8_direction}, M9 routing direction heuristic: {m9_direction}")

if m8:
    if m8_direction == "vertical":
         iop.addHorLayer(m8) # Use M8 for horizontal pins (vertical access wires)
         print("[INFO] Added metal8 as horizontal pin layer based on vertical routing direction heuristic.")
    elif m8_direction == "horizontal":
         iop.addVerLayer(m8) # Use M8 for vertical pins (horizontal access wires)
         print("[INFO] Added metal8 as vertical pin layer based on horizontal routing direction heuristic.")
    else:
        print("[WARNING] Could not determine direction for metal8. Skipping IO placement on metal8.")
else:
    print("[WARNING] Metal layer metal8 not found for IO placement. Skipping.")

if m9:
    if m9_direction == "horizontal":
        iop.addVerLayer(m9) # Use M9 for vertical pins (horizontal access wires)
        print("[INFO] Added metal9 as vertical pin layer based on horizontal routing direction heuristic.")
    elif m9_direction == "vertical":
        iop.addHorLayer(m9) # Use M9 for horizontal pins (vertical access wires)
        print("[INFO] Added metal9 as horizontal pin layer based on vertical routing direction heuristic.")
    else:
        print("[WARNING] Could not determine direction for metal9. Skipping IO placement on metal9.")
else:
    print("[WARNING] Metal layer metal9 not found for IO placement. Skipping.")


# Run IO placement annealing
try:
    # True for random mode, False for deterministic. Random mode might give better results.
    iop.runAnnealing(True)
    print("[INFO] IO placement complete.")
except Exception as e:
    print(f"[ERROR] Failed during IO placement: {e}")
    # Non-fatal if design has few pins or pins are pre-placed. Continue but warn.
    print("[WARNING] IO placement failed.")


# 4. Macro Placement
print("\n[INFO] Performing macro placement...")
# Identify macro instances in the design
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    print(f"[INFO] Found {len(macros)} macros. Running macro placement.")
    mpl = design.getMacroPlacer()

    # Set macro placement parameters from prompt
    halo_um = 5.0 # Halo around each macro (other cells/halos cannot enter)
    halo_width_um = halo_um
    halo_height_um = halo_um

    # Define the fence region for macros - usually the core area
    core = block.getCoreArea()
    fence_lx_um = block.dbuToMicrons(core.xMin())
    fence_ly_um = block.dbuToMicrons(core.yMin())
    fence_ux_um = block.dbuToMicrons(core.xMax())
    fence_uy_um = block.dbuToMicrons(core.yMax())

    # Find Metal4 layer level for macro pin snapping (helps access)
    snap_layer = tech.findLayer("metal4")
    snap_layer_level = snap_layer.getRoutingLevel() if snap_layer else 0 # Default to 0 if layer not found

    # Run macro placement
    try:
        mpl.place(
            num_threads = 64, # Number of threads for placement
            max_num_macro = len(macros), # Place all found macros
            min_num_macro = 0,
            max_num_inst = 0, # No limit on std cells within macro placement scope
            min_num_inst = 0,
            tolerance = 0.1,
            max_num_level = 2,
            coarsening_ratio = 10.0,
            large_net_threshold = 50,
            signature_net_threshold = 50,
            halo_width = halo_width_um, # Macro halo width in microns
            halo_height = halo_height_um, # Macro halo height in microns
            fence_lx = fence_lx_um, # Fence lower left x in microns
            fence_ly = fence_ly_um, # Fence lower left y in microns
            fence_ux = fence_ux_um, # Fence upper right x in microns
            fence_uy = fence_uy_um, # Fence upper right y in microns
            area_weight = 0.1, # Example weights, adjust based on design/tool
            outline_weight = 100.0,
            wirelength_weight = 100.0,
            guidance_weight = 10.0,
            fence_weight = 10.0,
            boundary_weight = 50.0,
            notch_weight = 10.0,
            macro_blockage_weight = 10.0,
            pin_access_th = 0.0,
            target_util = target_utilization, # Target utilization for std cells around macros
            target_dead_space = 0.05,
            min_ar = 0.33,
            snap_layer = snap_layer_level, # Layer level for macro pin snapping
            bus_planning_flag = False,
            report_directory = "" # Directory for reports
        )
        print("[INFO] Macro placement complete.")
    except Exception as e:
        print(f"[ERROR] Failed during macro placement: {e}")
        print("[ERROR] Macro placement failed.")
        # This is often critical, might need to exit or handle carefully.
        # For this script, we'll exit as subsequent steps depend on macro placement.
        exit(1)

else:
    print("[INFO] No macros found. Skipping macro placement.")


# 5. Detailed Placement (Initial - before CTS)
# Detailed placement refines cell locations. Often run after global placement
# and again after CTS. Prompt asks for standard cell placement after macros,
# and then detailed placement with specific displacement limits, which fits
# the description of a final detailed placement step. However, an initial
# detailed placement after global/macro placement is standard practice.
# We will perform an initial detailed placement here and a final one after CTS.
print("\n[INFO] Running initial detailed placement...")
dp = design.getOpendp()

# Remove filler cells before placement to allow cells to move into filler areas
# This assumes fillers might exist from a previous step or read DEF
dp.removeFillers()

# Get site dimensions to calculate displacement units based on site grid
rows = block.getRows()
if not rows:
     print("[ERROR] No rows found. Cannot perform detailed placement.")
     exit(1)
site = rows[0].getSite()
site_width_dbu = site.getWidth()
site_height_dbu = site.getHeight()

# Run initial detailed placement. Using 0.0, 0.0 allows default displacement limits.
try:
    dp.detailedPlacement(0.0, 0.0, "", False)
    print("[INFO] Initial detailed placement complete.")
except Exception as e:
    print(f"[ERROR] Failed during initial detailed placement: {e}")
    print("[ERROR] Initial detailed placement failed.")
    # This is often critical.
    exit(1)


# 6. Clock Tree Synthesis (CTS)
# CTS is performed after initial placement but before final detailed placement and routing.
print(f"\n[INFO] Running CTS for clock '{clock_name}'...")
cts = design.getTritonCts()

# Configure clock buffers - use BUF_X3 as specified
buffer_cell = "BUF_X3"
cts.setBufferList(buffer_cell) # Set the list of available buffers
cts.setRootBuffer(buffer_cell) # Set the buffer to use at the clock root
cts.setSinkBuffer(buffer_cell) # Set the buffer to use at the clock sinks

# Run CTS
try:
    cts.runTritonCts()
    print("[INFO] CTS complete.")
except Exception as e:
    print(f"[ERROR] Failed during CTS: {e}")
    print("[ERROR] CTS failed.")
    # CTS failure is critical.
    exit(1)


# 7. Detailed Placement (Final - after CTS)
# Detailed placement is typically run again after CTS to clean up placement shifts
# caused by buffer insertions and other CTS optimizations.
print("\n[INFO] Running final detailed placement...")
# Reuse the detailed placer object `dp`

# Get site dimensions again (should be the same)
site = block.getRows()[0].getSite()
site_width_dbu = site.getWidth()
site_height_dbu = site.getHeight()

# Define maximum allowed displacement in microns from prompt
max_disp_x_um = 0.5
max_disp_y_um = 1.0

# Convert maximum displacement from microns to DBU
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

# Convert DBU displacement to displacement per site tile width/height for the function call
# This calculation handles cases where site width/height are 0, though typical core sites are non-zero.
max_disp_x_site = max_disp_x_dbu / site_width_dbu if site_width_dbu > 0 else 0
max_disp_y_site = max_disp_y_dbu / site_height_dbu if site_height_dbu > 0 else 0


# Remove filler cells first if they were inserted earlier (e.g., read from a DEF with fillers)
# If fillers are only inserted *after* final DP, this is redundant but harmless.
dp.removeFillers()

# Run final detailed placement with specified displacement limits
print(f"[INFO] Running final detailed placement with max displacement x={max_disp_x_um}um ({max_disp_x_site:.3f} site units), y={max_disp_y_um}um ({max_disp_y_site:.3f} site units)...")
try:
    dp.detailedPlacement(max_disp_x_site, max_disp_y_site, "", False)
    print("[INFO] Final detailed placement complete.")
except Exception as e:
    print(f"[ERROR] Failed during final detailed placement: {e}")
    print("[ERROR] Final detailed placement failed.")
    exit(1)


# 8. Filler Insertion (After final detailed placement)
print("\n[INFO] Inserting filler cells...")
filler_masters = list()
# Find filler cells in the loaded libraries based on their type (CORE_SPACER)
filler_cells_prefix = "FILLCELL_" # Prefix for naming inserted filler instances
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

if len(filler_masters) == 0:
    print("[WARNING] No CORE_SPACER filler cells found in library! Cannot insert fillers.")
else:
    # Perform filler placement using the detailed placer object
    try:
        dp.fillerPlacement(filler_masters = filler_masters,
                         prefix = filler_cells_prefix,
                         verbose = False) # Set verbose to True for detailed output
        print("[INFO] Filler cell insertion complete.")
    except Exception as e:
        print(f"[ERROR] Failed during filler cell insertion: {e}")
        print("[ERROR] Filler cell insertion failed.")
        # Filler insertion failure might not be fatal, but can affect routing/timing. Continue but warn.
        print("[WARNING] Filler insertion failed.")


# 9. PDN Construction
print("\n[INFO] Constructing Power Delivery Network (PDN)...")
# Set up global power/ground connections
# Iterate through all nets and mark VDD/VSS nets as special
for net in block.getNets():
    if net.getSigType() == "POWER" or net.getSigType() == "GROUND":
        net.setSpecial()

# Find existing power and ground nets or create them if they don't exist
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")
switched_power = None # Placeholder, no switched power specified
secondary = list() # Placeholder, no secondary power nets specified

# Create VDD/VSS nets if needed
if VDD_net is None:
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSigType("POWER")
    print("[INFO] Created new VDD net.")
if VSS_net is None:
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSigType("GROUND")
    print("[INFO] Created new VSS net.")

# Ensure VDD/VSS nets are marked special after creation
VDD_net.setSpecial()
VSS_net.setSpecial()


# Connect power pins of instances to the global VDD/VSS nets
# Use addGlobalConnect with common pin patterns from standard cells
# Apply the global connections - must be done after nets are special
try:
    block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
    block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDPE$", net = VDD_net, do_connect = True)
    block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDCE$", net = VDD_net, do_connect = True)
    block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
    block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSSE$", net = VSS_net, do_connect = True)
    # Apply the global connections
    block.globalConnect()
    print("[INFO] Global power/ground connections applied.")
except Exception as e:
    print(f"[ERROR] Failed during global power/ground connect: {e}")
    print("[ERROR] Global power/ground connect failed.")
    # This can be critical, especially if PDN generation relies on it.
    # Continue but warn.
    print("[WARNING] Global power/ground connections might be incomplete.")


# Configure power domains
pdngen = design.getPdnGen()
# Set the core voltage domain with the primary power and ground nets
pdngen.setCoreDomain(power = VDD_net, switched_power = switched_power, ground = VSS_net, secondary = secondary)


# Define PDN dimensions in microns from prompt and convert to DBU
m1_width_um = 0.07
m4_width_um = 1.2
m4_spacing_um = 1.2
m4_pitch_um = 6.0
m7_width_um = 1.4
m7_spacing_um = 1.4
m7_pitch_um = 10.8

core_ring_width_um = 2.0
core_ring_spacing_um = 2.0 # Prompt says 2,2 for M7/M8 rings

macro_strap_width_um = 1.2 # Prompt M5/M6 grid width 1.2
macro_strap_spacing_um = 1.2 # Prompt M5/M6 grid spacing 1.2
macro_strap_pitch_um = 6.0 # Prompt M5/M6 grid pitch 6.0

macro_ring_width_um = 2.0 # Prompt M5/M6 ring width 2
macro_ring_spacing_um = 2.0 # Prompt M5/M6 ring spacing 2

via_cut_pitch_um = 2.0 # Pitch of via between two parallel grids
offset_um = 0.0 # Offset is 0um for all cases as per prompt

# Convert microns to DBU
m1_width_dbu = design.micronToDBU(m1_width_um)
m4_width_dbu = design.micronToDBU(m4_width_um)
m4_spacing_dbu = design.micronToDBU(m4_spacing_um)
m4_pitch_dbu = design.micronToDBU(m4_pitch_um)
m7_width_dbu = design.micronToDBU(m7_width_um)
m7_spacing_dbu = design.micronToDBU(m7_spacing_um)
m7_pitch_dbu = design.micronToDBU(m7_pitch_um)

core_ring_width_dbu = design.micronToDBU(core_ring_width_um)
core_ring_spacing_dbu = design.micronToDBU(core_ring_spacing_um)

macro_strap_width_dbu = design.micronToDBU(macro_strap_width_um)
macro_strap_spacing_dbu = design.micronToDBU(macro_strap_spacing_um)
macro_strap_pitch_dbu = design.micronToDBU(macro_strap_pitch_um)

macro_ring_width_dbu = design.micronToDBU(macro_ring_width_um)
macro_ring_spacing_dbu = design.micronToDBU(macro_ring_spacing_um)

via_cut_pitch_dbu = design.micronToDBU(via_cut_pitch_um)
offset_dbu = design.micronToDBU(offset_um)

# Get metal layers required for PDN
m1 = tech.findLayer("metal1")
m4 = tech.findLayer("metal4")
m5 = tech.findLayer("metal5")
m6 = tech.findLayer("metal6")
m7 = tech.findLayer("metal7")
m8 = tech.findLayer("metal8")
m9 = tech.findLayer("metal9") # M9 might be used implicitly for IO pins connected to power nets

# Check if required layers exist
required_layers = {"metal1":m1, "metal4":m4, "metal5":m5, "metal6":m6, "metal7":m7, "metal8":m8}
missing_layers = [name for name, layer in required_layers.items() if layer is None]
if missing_layers:
    print(f"[ERROR] One or more required metal layers for PDN not found: {', '.join(missing_layers)}")
    exit(1)

# Get layer orientations for via calculations
m1_orient = get_layer_routing_direction_heuristic(m1)
m4_orient = get_layer_routing_direction_heuristic(m4)
m5_orient = get_layer_routing_direction_heuristic(m5)
m6_orient = get_layer_routing_direction_heuristic(m6)
m7_orient = get_layer_routing_direction_heuristic(m7)
m8_orient = get_layer_routing_direction_heuristic(m8)

print(f"[INFO] PDN Layer Orientations (heuristic): M1:{m1_orient}, M4:{m4_orient}, M5:{m5_orient}, M6:{m6_orient}, M7:{m7_orient}, M8:{m8_orient}")

# Create power grid for standard cells (Core Grid)
# Get the core voltage domain
domain = pdngen.findDomain("Core")
if not domain:
    print("[ERROR] 'Core' power domain not found. Ensure setCoreDomain was successful.")
    exit(1)

# Create the main core grid structure for standard cells
print(f"[INFO] Creating core grid for domain '{domain.getName()}'...")
pdngen.makeCoreGrid(domain = domain,
    name = "core_grid", # A descriptive name
    starts_with = pdn.GROUND, # Start with ground net (common practice)
    pin_layers = [], # Not specified in prompt
    generate_obstructions = [], # Not specified
    powercell = None, # Not specified
    powercontrol = None, # Not specified
    powercontrolnetwork = "STAR", # Using STAR as in examples
    blockages = []) # No specific blockages mentioned

# Get the core grid object (assuming one core grid named "core_grid")
core_grid = pdngen.findGrid("core_grid")
if not core_grid:
     print("[ERROR] Core grid 'core_grid' not found after creation attempt.")
     exit(1)

# Add PDN structures to the core grid (Standard Cells)
print("[INFO] Adding straps and rings to core grid...")
# M1 followpin stripes (typically horizontal, following standard cell rails)
# Followpin is for power/ground connections that follow the standard cell rows
pdngen.makeFollowpin(grid = core_grid,
    layer = m1,
    width = m1_width_dbu,
    extend = pdn.CORE) # Extend within the core area
print("[INFO] Added metal1 followpin stripes.")

# M4 straps (as specified for 'macros' in the core list, width 1.2, spacing 1.2, pitch 6)
# Assuming this means a grid on M4 within the core area, likely for connecting macros
# or higher-level std cell distribution, distinct from the macro instance grid on M5/M6.
pdngen.makeStrap(grid = core_grid,
    layer = m4,
    width = m4_width_dbu,
    spacing = m4_spacing_dbu,
    pitch = m4_pitch_dbu,
    offset = offset_dbu,
    number_of_straps = 0, # Auto-calculate number of straps based on pitch/area
    snap = False, # Do not snap to grid unless required
    starts_with = pdn.GRID, # Relative to the grid origin
    extend = pdn.CORE, # Extend within the core area
    nets = []) # Apply to all nets in the domain (VDD/VSS)
print("[INFO] Added metal4 straps (for standard cells/macros) to core grid.")

# M7 straps (as specified, width 1.4, spacing 1.4, pitch 10.8)
pdngen.makeStrap(grid = core_grid,
    layer = m7,
    width = m7_width_dbu,
    spacing = m7_spacing_dbu,
    pitch = m7_pitch_dbu,
    offset = offset_dbu,
    number_of_straps = 0,
    snap = False,
    starts_with = pdn.GRID,
    extend = pdn.CORE, # Extend within the core area
    nets = [])
print("[INFO] Added metal7 straps to core grid.")

# NOTE: M8 straps were not explicitly requested in the prompt, only M8 rings.
# The M8 strap definition from the previous script has been removed to adhere strictly to the prompt.
print("[INFO] Metal8 straps not added to core grid as not specified in prompt.")

# M7/M8 rings around core area
# Prompt: power rings on M7 and M8... width 2 and 2 um, spacing 2 and 2 um.
# Assuming M7 is for horizontal segments and M8 for vertical segments based on common layer directions heuristic.
pdngen.makeRing(grid = core_grid,
    layer0 = m7, # Layer 0 for ring (e.g., horizontal segments if M7 is horizontal)
    width0 = core_ring_width_dbu,
    spacing0 = core_ring_spacing_dbu,
    layer1 = m8, # Layer 1 for ring (e.g., vertical segments if M8 is vertical)
    width1 = core_ring_width_dbu,
    spacing1 = core_ring_spacing_dbu,
    starts_with = pdn.GRID, # Start relative to the grid definition (often core boundary)
    offset = [offset_dbu for _ in range(4)], # Offset from core boundary (left, bottom, right, top) - 0 offset
    pad_offset = [offset_dbu for _ in range(4)], # Offset from pad boundary (not applicable here) - 0 offset
    extend = False, # Rings stay around the specified boundary (core area)
    pad_pin_layers = [], # No pads connecting to core ring
    nets = [], # Apply to VDD/VSS
    allow_out_of_die = True) # Allow parts of the ring structure outside core but within die (common)
print("[INFO] Added metal7/metal8 rings around core area.")


# Create via connections between standard cell grid layers
# Via cut pitch is 2um between parallel grids -> interpreted as 2um pitch for via arrays between layers with orthogonal directions
# Calculate via pitch based on transition between layer orientations
m1_m4_cut_pitch_x = via_cut_pitch_dbu if (m1_orient != m4_orient and m4_orient == 'vertical') else design.micronToDBU(0)
m1_m4_cut_pitch_y = via_cut_pitch_dbu if (m1_orient != m4_orient and m4_orient == 'horizontal') else design.micronToDBU(0)

m4_m7_cut_pitch_x = via_cut_pitch_dbu if (m4_orient != m7_orient and m7_orient == 'vertical') else design.micronToDBU(0)
m4_m7_cut_pitch_y = via_cut_pitch_dbu if (m4_orient != m7_orient and m7_orient == 'horizontal') else design.micronToDBU(0)

# No M7-M8 strap connections needed for core grid as M8 straps were not added per prompt.
print(f"[INFO] Via cut pitches (based on strap layers in core grid): M1-M4 ({design.dbuToMicrons(m1_m4_cut_pitch_x):.3f},{design.dbuToMicrons(m1_m4_cut_pitch_y):.3f})um, M4-M7 ({design.dbuToMicrons(m4_m7_cut_pitch_x):.3f},{design.dbuToMicrons(m4_m7_cut_pitch_y):.3f})um")

pdngen.makeConnect(grid = core_grid, layer0 = m1, layer1 = m4,
                   cut_pitch_x = m1_m4_cut_pitch_x, cut_pitch_y = m1_m4_cut_pitch_y,
                   vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
print("[INFO] Added M1-M4 via connections for core grid straps.")

pdngen.makeConnect(grid = core_grid, layer0 = m4, layer1 = m7,
                   cut_pitch_x = m4_m7_cut_pitch_x, cut_pitch_y = m4_m7_cut_pitch_y,
                   vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
print("[INFO] Added M4-M7 via connections for core grid straps.")


# Create power grid for macro blocks (Instance Grids) if macros exist
# Prompt: If the design has macros, build power rings and power grids for macros on M5 and M6...
# Set width/spacing of M5/M6 grids to 1.2um, pitch 6um.
# Set width/spacing of M5/M6 rings to 2um.
# Via pitch 2um between parallel grids.
# Offset 0 for all cases.
if len(macros) > 0:
    print(f"[INFO] Design has macros. Creating instance grids for macros on M5/M6...")
    # Use the macro halo distance as the boundary for the instance grid relative to the macro
    # PDN instance grid halo is added *to* the macro bounding box for the grid area.
    # The prompt asks for 5um halo around macros for standard cells, and macro PDN on M5/M6.
    # Let's use the 5um halo for the *boundary* of the instance grid relative to the macro,
    # meaning the grid will extend 5um out from the macro edges.
    macro_grid_halo_dbu = [design.micronToDBU(halo_um) for i in range(4)] # [left, bottom, right, top]

    for macro in macros:
        print(f"[INFO] Creating instance grid for macro '{macro.getName()}'...")
        # Create separate power grid for each macro instance
        # Assuming macros belong to the core domain for power
        pdngen.makeInstanceGrid(domain = domain,
            name = f"CORE_macro_grid_{macro.getName()}", # Unique grid name per macro instance
            starts_with = pdn.GROUND, # Start with ground net
            inst = macro, # Associate grid with this macro instance
            halo = macro_grid_halo_dbu, # Halo defines the boundary of the instance grid relative to the macro
            pg_pins_to_boundary = True, # Connect macro PG pins to the instance grid boundary
            default_grid = False, # Not the default grid
            generate_obstructions = [], # Not specified
            is_bump = False, # Assuming not bump connection
            blockages = []) # No specific blockages

        # Get the instance grid object for the current macro
        macro_grid_name = f"CORE_macro_grid_{macro.getName()}"
        macro_grid = pdngen.findGrid(macro_grid_name)
        if not macro_grid:
             print(f"[ERROR] Instance grid '{macro_grid_name}' not found after creation attempt.")
             continue # Skip adding features to this macro grid if creation failed

        # Add PDN structures to the instance grid for the current macro
        # Add M5 straps for macro (width 1.2, spacing 1.2, pitch 6)
        pdngen.makeStrap(grid = macro_grid, # Add strap to the grid object
            layer = m5,
            width = macro_strap_width_dbu,
            spacing = macro_strap_spacing_dbu,
            pitch = macro_strap_pitch_dbu,
            offset = offset_dbu,
            number_of_straps = 0,
            snap = True, # Snap straps to the grid within the instance grid
            starts_with = pdn.GRID,
            extend = pdn.CORE, # Extend within the instance grid core area (the halo region)
            nets = []) # Apply to all nets in the domain (VDD/VSS)
        print(f"[INFO] Added metal5 straps for macro '{macro.getName()}'.")

        # Add M6 straps for macro (width 1.2, spacing 1.2, pitch 6)
        pdngen.makeStrap(grid = macro_grid,
            layer = m6,
            width = macro_strap_width_dbu,
            spacing = macro_strap_spacing_dbu,
            pitch = macro_strap_pitch_dbu,
            offset = offset_dbu,
            number_of_straps = 0,
            snap = True,
            starts_with = pdn.GRID,
            extend = pdn.CORE,
            nets = [])
        print(f"[INFO] Added metal6 straps for macro '{macro.getName()}'.")


        # M5/M6 rings around macro instance grid (width 2, spacing 2)
        # Assuming M5 is horizontal and M6 is vertical based on common layer directions heuristic.
        pdngen.makeRing(grid = macro_grid,
            layer0 = m5, # Layer 0 for ring (e.g., horizontal segments if M5 is horizontal)
            width0 = macro_ring_width_dbu,
            spacing0 = macro_ring_spacing_dbu,
            layer1 = m6, # Layer 1 for ring (e.g., vertical segments if M6 is vertical)
            width1 = macro_ring_width_dbu,
            spacing1 = macro_ring_spacing_dbu,
            starts_with = pdn.GRID, # Start relative to the instance grid boundary (the halo region)
            offset = [offset_dbu for _ in range(4)], # Offset from instance grid boundary (0 offset)
            pad_offset = [offset_dbu for _ in range(4)], # Not applicable - 0 offset
            extend = False, # Rings stay around the instance grid boundary
            pad_pin_layers = [],
            nets = [],
            allow_out_of_die = False) # Rings should stay within instance grid area/halo
        print(f"[INFO] Added metal5/metal6 rings for macro '{macro.getName()}'.")

        # Create via connections within macro grid and to core grid
        # Connections needed:
        # - Within macro grid: M5 to M6
        # - Between macro grid and core grid: Connect macro grid layers (M5, M6) to nearby core grid layers (M4, M7).
        #   The core grid has M1, M4, M7, M8 rings. Macro grid has M5, M6 straps/rings.
        #   Common connections would be M4 (core) <-> M5 (macro) and M6 (macro) <-> M7 (core).

        # M4 (core) <-> M5 (macro) connections
        m4_m5_cut_pitch_x = via_cut_pitch_dbu if (m4_orient != m5_orient and m5_orient == 'vertical') else design.micronToDBU(0)
        m4_m5_cut_pitch_y = via_cut_pitch_dbu if (m4_orient != m5_orient and m5_orient == 'horizontal') else design.micronToDBU(0)
        pdngen.makeConnect(grid = macro_grid, layer0 = m4, layer1 = m5, # Connect M4 (core grid layer) to M5 (macro grid layer)
                   cut_pitch_x = m4_m5_cut_pitch_x, cut_pitch_y = m4_m5_cut_pitch_y,
                   vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
        print(f"[INFO] Added M4-M5 via connections for macro '{macro.getName()}'.")

        # M5 <-> M6 (within macro grid) connections
        m5_m6_cut_pitch_x = via_cut_pitch_dbu if (m5_orient != m6_orient and m6_orient == 'vertical') else design.micronToDBU(0)
        m5_m6_cut_pitch_y = via_cut_pitch_dbu if (m5_orient != m6_orient and m6_orient == 'horizontal') else design.micronToDBU(0)
        pdngen.makeConnect(grid = macro_grid, layer0 = m5, layer1 = m6, # Connect M5 to M6 (within macro grid)
                   cut_pitch_x = m5_m6_cut_pitch_x, cut_pitch_y = m5_m6_cut_pitch_y,
                   vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
        print(f"[INFO] Added M5-M6 via connections for macro '{macro.getName()}'.")

        # M6 (macro) <-> M7 (core) connections
        m6_m7_cut_pitch_x = via_cut_pitch_dbu if (m6_orient != m7_orient and m7_orient == 'vertical') else design.micronToDBU(0)
        m6_m7_cut_pitch_y = via_cut_pitch_dbu if (m6_orient != m7_orient and m7_orient == 'horizontal') else design.micronToDBU(0)
        pdngen.makeConnect(grid = macro_grid, layer0 = m6, layer1 = m7, # Connect M6 (macro grid layer) to M7 (core grid layer)
                   cut_pitch_x = m6_m7_cut_pitch_x, cut_pitch_y = m6_m7_cut_pitch_y,
                   vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
        print(f"[INFO] Added M6-M7 via connections for macro '{macro.getName()}'.")

else:
    print("[INFO] No macros found. Skipping macro PDN construction.")


# Generate the final power delivery network shapes in the database
print("[INFO] Building PDN shapes...")
try:
    pdngen.checkSetup() # Verify the PDN configuration
    pdngen.buildGrids(False) # Build the power grid geometries. False = do not generate obstructions (usually preferred later).
    pdngen.writeToDb(True) # Write the generated power grid shapes to the design database. True = Commit changes immediately.
    # pdngen.resetShapes() # Clear temporary shapes used during generation (optional, might help with memory)
    print("[INFO] PDN construction complete.")
except Exception as e:
    print(f"[ERROR] Failed during PDN construction: {e}")
    print("[ERROR] PDN construction failed.")
    # PDN construction is critical for subsequent steps.
    exit(1)


# 10. IR Drop Analysis
# IR drop analysis typically requires the power grid and parasitic models (.spef).
# Assuming parasitic models are loaded prior to this script or will be loaded by the tool.
print("\n[INFO] Running IR Drop analysis...")
try:
    irdrop = ord.get_ir_drop()
    # Set the power and ground nets for the IR drop tool
    irdrop.set_power_net(VDD_net)
    irdrop.set_ground_net(VSS_net)
    # Set operating voltage if not already set (e.g., from SDC or technology)
    # Example: irdrop.set_voltage(1.1) # Assuming 1.1V operating voltage, replace with actual if known or required

    # The request asks to analyze M1 nodes. The 'analyze()' function typically
    # analyzes the entire grid. Reporting tools might allow filtering by layer.
    # OpenROAD's IR drop analysis usually runs on the whole design;
    # reporting can sometimes be filtered by layer or net. The analyze() call
    # performs the full analysis.
    irdrop.analyze()
    print("[INFO] IR Drop analysis complete.")
    # Report IR drop results. Check OpenROAD documentation for specific report filtering options if needed.
    # The default report typically shows worst cases and can be filtered manually or via tool parameters.
    irdrop.report()
except Exception as e:
    print(f"[ERROR] Failed during IR Drop analysis: {e}")
    print("[ERROR] IR Drop analysis failed.")
    # IR Drop failure might not be fatal for routing, but is for analysis goals. Continue but warn.
    print("[WARNING] IR Drop analysis failed.")


# 11. Power Report
# Power analysis requires static timing analysis (STA) and power models (.db or .lib).
# Assuming timing libraries (.lib) and power models are loaded prior to this script.
print("\n[INFO] Running Power analysis...")
try:
    sta = ord.get_sta()
    # Perform power analysis
    sta.power_analysis()
    print("[INFO] Power analysis complete.")
    # Print the power report, which usually includes switching, leakage, internal, and total power.
    sta.print_power()
except Exception as e:
    print(f"[ERROR] Failed during Power analysis: {e}")
    print("[ERROR] Power analysis failed.")
    # Power analysis failure is not fatal for routing. Continue but warn.
    print("[WARNING] Power analysis failed.")


# 12. Global Routing
print("\n[INFO] Running global routing...")
grt = design.getGlobalRouter()

# Set routing layer ranges (M1 to M6)
# Get routing levels for Metal1 and Metal6
m1 = tech.findLayer("metal1") # Re-fetch in case needed, or reuse
m6 = tech.findLayer("metal6") # Re-fetch in case needed, or reuse

if not m1 or not m6:
     print("[ERROR] Metal1 or Metal6 layer not found. Cannot set routing layers.")
     exit(1)

m1_route_level = m1.getRoutingLevel()
m6_route_level = m6.getRoutingLevel()

grt.setMinRoutingLayer(m1_route_level) # Minimum routing layer for signal nets
grt.setMaxRoutingLayer(m6_route_level) # Maximum routing layer for signal nets
# Prompt doesn't specify clock routing layers, default is usually all layers.
# Setting explicitly to M1-M6 aligns with the signal routing range requested.
grt.setMinLayerForClock(m1_route_level) # Minimum routing layer for clock nets
grt.setMaxLayerForClock(m6_route_level) # Maximum routing layer for clock nets
print(f"[INFO] Routing layers set from level {m1_route_level} (Metal1) to {m6_route_level} (Metal6).")


# Set number of iterations for global router from prompt
grt.setIterations(10)
print(f"[INFO] Global router iterations set to {grt.getIterations()}.")

# Set congestion adjustment (example value from prior scripts or documentation)
# Not explicitly specified in the prompt, using a common value.
grt.setAdjustment(0.5)
grt.setVerbose(True) # Enable verbose output

# Run global routing
try:
    grt.globalRoute(True) # True typically routes clocks first
    print("[INFO] Global routing complete.")
except Exception as e:
    print(f"[ERROR] Failed during global routing: {e}")
    print("[ERROR] Global routing failed.")
    # Global routing failure is critical.
    exit(1)


# 13. Detailed Routing
print("\n[INFO] Running detailed routing...")
drter = design.getTritonRoute()
# Create a parameter structure for the detailed router
params = drt.ParamStruct()

# Configure detailed routing parameters (using values from examples/defaults)
# Set bottom and top routing layers based on global routing range (M1 to M6)
params.bottomRoutingLayer = m1.getName() # Set bottom routing layer by name
params.topRoutingLayer = m6.getName() # Set top routing layer by name
print(f"[INFO] Detailed router layers set from {params.bottomRoutingLayer} to {params.topRoutingLayer}.")

# Other parameters - keeping reasonable defaults or values from examples if not specified
params.outputMazeFile = "" # Output file paths for debugging/analysis (leave empty if not needed)
params.outputDrcFile = ""
params.outputCmapFile = ""
params.outputGuideCoverageFile = ""
params.dbProcessNode = "" # Process node identifier from technology file (optional)
params.enableViaGen = True # Enable via generation (usually True)
params.drouteEndIter = 1 # Number of detailed routing iterations (1 is common for initial DR)
params.viaInPinBottomLayer = "" # Not specified in prompt (technology specific)
params.viaInPinTopLayer = "" # Not specified in prompt (technology specific)
params.orSeed = -1 # Random seed (-1 uses time, positive for deterministic)
params.orK = 0 # Router parameter (tool specific)
params.verbose = 1 # Verbosity level (1 is standard)
params.cleanPatches = True # Clean up routing patches
params.doPa = True # Perform pin access (essential)
params.minAccessPoints = 1 # Minimum access points for pin connections (tool specific)
params.saveGuideUpdates = False # Save guide updates (for debugging)
params.singleStepDR = False # Run detailed routing in a single step (if multiple iterations, use False)


# Set the configured parameters for the detailed router
drter.setParams(params)

# Run detailed routing
try:
    drter.main() # The main detailed routing function
    print("[INFO] Detailed routing complete.")
except Exception as e:
    print(f"[ERROR] Failed during detailed routing: {e}")
    print("[ERROR] Detailed routing failed.")
    # Detailed routing failure is critical.
    exit(1)


# 14. Save DEF
print("\n[INFO] Saving final DEF file...")
# Write the final design database to a DEF file
try:
    design.writeDef("final.def")
    print("[INFO] Final DEF saved as final.def")
except Exception as e:
    print(f"[ERROR] Failed to write final DEF file: {e}")
    print("[ERROR] Saving final DEF failed.")

# Note: Prompt did not explicitly ask to save verilog or odb, only DEF.
# Optional: Save Verilog and ODB files as well if needed in your flow.
# try:
#     print("[INFO] Saving final Verilog netlist...")
#     design.evalTclString("write_verilog final.v")
#     print("[INFO] Final Verilog saved as final.v")
# except Exception as e:
#     print(f"[WARNING] Failed to write final Verilog: {e}")
#
# try:
#     print("[INFO] Saving final ODB database...")
#     design.writeDb("final.odb")
#     print("[INFO] Final ODB saved as final.odb")
# except Exception as e:
#     print(f"[WARNING] Failed to write final ODB: {e}")


print("\nOpenROAD Python script execution finished.")