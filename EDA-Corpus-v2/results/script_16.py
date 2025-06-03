# Imports
import odb
import pdn
import drt
import openroad as ord

# --- Configuration ---
# Clock parameters
clock_port_name = "clk"
clock_name = "core_clock"
clock_period_ns = 50
clock_period_ps = clock_period_ns * 1000 # Convert clock period from ns to ps

# Floorplan parameters
target_utilization = 0.35 # Desired core area utilization percentage
core_to_die_margin_um = 12.0 # Margin distance from core boundary to die boundary in microns

# Placement parameters
macro_halo_um = 5.0 # Halo size around macros for placement and PDN exclusion in microns
# Note: Minimum macro separation (5um) is typically handled by the macro placer's packing algorithm and the halo.
# There isn't a direct 'min_distance_between_macros' parameter exposed in the mpl.place API based on examples.
detailed_placement_max_disp_x_um = 0.5 # Maximum allowed displacement in X for detailed placement in microns
detailed_placement_max_disp_y_um = 0.5 # Maximum allowed displacement in Y for detailed placement in microns

# CTS parameters
cts_buffer_name = "BUF_X2" # Standard cell name to use for clock buffers
wire_rc_resistance = 0.03574 # Unit resistance for RC calculations
wire_rc_capacitance = 0.07516 # Unit capacitance for RC calculations

# PDN parameters (widths, spacings, pitches, offset, via pitch in microns)
std_cell_m1_width_um = 0.07 # Width of followpin straps on metal1 for standard cells
std_cell_m4_width_um = 1.2 # Width of power straps on metal4 for standard cells
std_cell_m4_spacing_um = 1.2 # Spacing between power straps on metal4
std_cell_m4_pitch_um = 6.0 # Pitch of power straps on metal4
std_cell_m7_width_um = 1.4 # Width of power straps on metal7 for standard cells
std_cell_m7_spacing_um = 1.4 # Spacing between power straps on metal7
std_cell_m7_pitch_um = 10.8 # Pitch of power straps on metal7

macro_m5_width_um = 1.2 # Width of power straps on metal5 for macros
macro_m5_spacing_um = 1.2 # Spacing between power straps on metal5 for macros
macro_m5_pitch_um = 6.0 # Pitch of power straps on metal5 for macros
macro_m6_width_um = 1.2 # Width of power straps on metal6 for macros
macro_m6_spacing_um = 1.2 # Spacing between power straps on metal6 for macros
macro_m6_pitch_um = 6.0 # Pitch of power straps on metal6 for macros

ring_m7_width_um = 4.0 # Width of power ring straps on metal7
ring_m7_spacing_um = 4.0 # Spacing between power ring straps on metal7
ring_m8_width_um = 4.0 # Width of power ring straps on metal8
ring_m8_spacing_um = 4.0 # Spacing between power ring straps on metal8

via_cut_pitch_um = 0.0 # Pitch for via cuts between parallel grid straps in microns (0 for dense)
pdn_offset_um = 0.0 # Offset distance for strap patterns and rings in microns (from grid/boundary edge)

# Routing Layer Names (adjust based on your technology LEF)
global_router_min_layer_name = "metal1" # Lowest metal layer for global routing
global_router_max_layer_name = "metal7" # Highest metal layer for global routing
detailed_router_min_layer_name = "metal1" # Lowest metal layer for detailed routing
detailed_router_max_layer_name = "metal7" # Highest metal layer for detailed routing

# --- Main Script ---

# Assume technology, LEF, and Verilog are already loaded and design is populated within the OpenROAD environment
# The 'design' object is usually available globally in the OpenROAD Python interpreter after reading inputs.

# Get the design object and necessary sub-objects
block = design.getBlock() # Get the top-level block object
db = ord.get_db() # Get the OpenDB database object
tech = db.getTech() # Get the technology object

# Find a standard cell site object required for floorplanning and placement
site = None
for s in tech.getSites():
    # Find a CORE site, which is typically used for standard cells
    if s.getClass() == "CORE":
        site = s
        break

if site is None:
    print("Error: No CORE site found in technology library! Cannot proceed with site-dependent steps (Floorplanning, Placement, Fillers).")
    # In a production flow, you would likely exit or raise an exception here.
    # For this example script, we will print the error and continue, but be aware subsequent steps relying on 'site' or rows may fail.

print("--- Starting Physical Design Flow ---")

# --- 1. Clock Setup ---
print("\n--- 1. Setting up clock ---")
# Create clock signal on the specified input port with a period and name
# evalTclString is used to execute OpenROAD TCL commands from Python
design.evalTclString(f"create_clock -period {clock_period_ps} [get_ports {clock_port_name}] -name {clock_name}")

# Find the clock net object in the design block after creation
clock_net = block.findNet(clock_name)
if clock_net:
    # Propagate the clock signal throughout the design for timing analysis and CTS
    design.evalTclString(f"set_propagated_clock [get_clocks {clock_name}]")
    print(f"Clock '{clock_name}' created and propagated.")
else:
     print(f"Warning: Clock net '{clock_name}' not found after creation. Cannot propagate clock. Please check clock_port_name.")

# Set the unit resistance and capacitance values for clock nets for RC extraction and timing analysis
design.evalTclString(f"set_wire_rc -clock -resistance {wire_rc_resistance} -capacitance {wire_rc_capacitance}")
# Set the unit resistance and capacitance values for regular signal nets
design.evalTclString(f"set_wire_rc -signal -resistance {wire_rc_resistance} -capacitance {wire_rc_capacitance}")
print("Wire RC values set.")
print("Clock setup complete.")

# --- 2. Floorplanning ---
print("\n--- 2. Performing floorplanning ---")
floorplan = design.getFloorplan() # Get the Floorplan object

# Initialize floorplan using the found site, target utilization, and core-to-die margin.
# This function calculates the core and die areas based on the total cell area and the specified constraints.
# Assumes 'site' object was found. If not, this will likely fail.
if site:
    floorplan.initFloorplan(
        site = site, # Standard cell site definition
        utilization = target_utilization, # Target utilization percentage for the core area
        core_to_die_margin = design.micronToDBU(core_to_die_margin_um) # Margin between core and die boundaries, converted to DBU
    )
    # Create placement tracks within the core area. Tracks are based on the site's row properties.
    floorplan.makeTracks()
    print(f"Floorplanning complete (target utilization={target_utilization:.2f}, margin={core_to_die_margin_um:.2f}um).")
else:
     print("Skipping floorplanning due to missing site.")

# Dump DEF file after floorplanning to visualize the created core and die areas, and tracks.
design.writeDef("floorplan.def")
print("Saved floorplan.def")

# --- 3. Pin Placement ---
print("\n--- 3. Performing pin placement ---")
io_placer = design.getIOPlacer() # Get the IOPlacer object
params = io_placer.getParameters() # Get the parameters object for configuration

# Set random seed for deterministic pin placement results if running with annealing
params.setRandSeed(42) # Example seed value

# Find metal layers by name for horizontal and vertical pin placement
m8_layer = tech.findLayer("metal8")
m9_layer = tech.findLayer("metal9")

# Add the found layers to the IO placer configuration
if m8_layer:
    io_placer.addHorLayer(m8_layer) # Add metal8 for horizontal pin connections
    print("Added metal8 for horizontal pin placement.")
else:
    print("Warning: metal8 layer not found for horizontal pin placement. Skipping.")
if m9_layer:
    io_placer.addVerLayer(m9_layer) # Add metal9 for vertical pin connections
    print("Added metal9 for vertical pin placement.")
else:
    print("Warning: metal9 layer not found for vertical pin placement. Skipping.")

# Run the IO placer algorithm (e.g., annealing or grid-based)
io_placer.runAnnealing(True) # True enables annealing mode for pin placement
print("Pin placement complete.")

# Dump DEF file after pin placement
design.writeDef("io_placed.def")
print("Saved io_placed.def")

# --- 4. Placement ---
print("\n--- 4. Performing placement ---")

# Identify macro blocks (instances whose master is a block/macro) in the design block
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

# Macro Placement (performs placement for macro instances if they exist)
if macros:
    print(f"Found {len(macros)} macros. Performing macro placement...")
    mpl = design.getMacroPlacer() # Get the MacroPlacer object
    core = block.getCoreArea() # Get the core area defined during floorplanning

    # Check if the core area is valid (non-zero dimensions) before using it as a fence
    if core.xMin() == 0 and core.yMin() == 0 and core.xMax() == 0 and core.yMax() == 0:
         print("Warning: Core area is zero or not defined. Skipping macro placement fence.")
         fence_params = {} # Use an empty dictionary if core area is invalid
    else:
         # Set fence parameters to constrain macros to be placed within the core area
         fence_params = {
            "fence_lx": block.dbuToMicrons(core.xMin()), # Left X boundary of fence (convert DBU to microns)
            "fence_ly": block.dbuToMicrons(core.yMin()), # Lower Y boundary of fence
            "fence_ux": block.dbuToMicrons(core.xMax()), # Upper X boundary of fence
            "fence_uy": block.dbuToMicrons(core.yMax()), # Upper Y boundary of fence
            "fence_weight": 10.0, # Example weight for the fence constraint
         }

    # Set macro placement parameters, including halo and fence (if core area is valid)
    mpl.place(
        num_threads = 64, # Example: Specify number of threads to use
        max_num_macro = len(macros), # Specify the maximum number of macros to place (place all found)
        halo_width = macro_halo_um, # Set halo size around each macro in microns (prevents std cells from being placed too close)
        halo_height = macro_halo_um,
        **fence_params, # Unpack fence_params dictionary if it's not empty, applying fence constraints
        # Other parameters control placer behavior (weights for area, wirelength, etc.)
        area_weight = 0.1,
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        target_util = 0.25, # Example target utilization within macro placement regions
        target_dead_space = 0.05, # Example target dead space
        min_ar = 0.33, # Example minimum aspect ratio for placement regions
        # snap_layer = 4, # Optional: Layer index to snap macro origins to. Omitted as it's tech-specific.
        bus_planning_flag = False # Disable bus planning during macro placement
    )
    print("Macro placement complete.")
else:
    print("No macros found. Skipping macro placement.")

# Global Placement (for standard cells)
print("Performing global placement...")
gpl = design.getReplace() # Get the RePlAce global placer object

# Configure global placer parameters for routability-driven placement
gpl.setTimingDrivenMode(False) # Set to True if timing optimization is desired during GP (requires timing setup)
gpl.setRoutabilityDrivenMode(True) # Enable routability optimization during GP
gpl.setUniformTargetDensityMode(True) # Distribute cell density uniformly across the core area

# Run the global placement steps (initial coarse placement followed by Nesterov optimization)
# Optional: gpl.setInitialPlaceMaxIter(10) # Set iterations for initial placement stage
# Optional: gpl.setNesterovPlaceMaxIter(100) # Set iterations for Nesterov-based legalization stage
gpl.doInitialPlace(threads = 4) # Run initial placement using 4 threads (example)
gpl.doNesterovPlace(threads = 4) # Run Nesterov placement using 4 threads (example)
gpl.reset() # Reset the placer state after completion
print("Global placement complete.")

# Detailed Placement (for standard cells)
# This refines the global placement results to fix overlaps and align cells to rows.
print("Performing detailed placement...")
opendp = design.getOpendp() # Get the OpenDP detailed placer object

# Need a site object to calculate the maximum displacement correctly (um to DBU)
site_for_dp = None
rows = block.getRows()
if rows:
    # Get the site from the first row if rows exist after global placement
    site_for_dp = rows[0].getSite()
elif site:
     # Otherwise, use the site found earlier during floorplanning if available
     site_for_dp = site

if site_for_dp:
    # Convert maximum allowed displacement from microns to DBU
    max_disp_x_dbu = design.micronToDBU(detailed_placement_max_disp_x_um)
    max_disp_y_dbu = design.micronToDBU(detailed_placement_max_disp_y_um)

    # Optional: Remove filler cells before detailed placement if they were inserted prematurely
    # Fillers are typically inserted *after* final detailed placement to fill row gaps.
    # opendp.removeFillers()

    # Perform the detailed placement
    opendp.detailedPlacement(
        max_disp_x_dbu, # Maximum allowed displacement in X direction (DBU)
        max_disp_y_dbu, # Maximum allowed displacement in Y direction (DBU)
        "", # Row pattern (empty string means apply to cells in all rows)
        False # Group placement (False places individual cells)
    )
    print(f"Detailed placement complete (max_displacement_x={detailed_placement_max_disp_x_um:.2f}um, max_displacement_y={detailed_placement_max_disp_y_um:.2f}um).")
else:
     print("Skipping detailed placement: Site information not available.")

# Dump DEF file after placement (capturing results of macro, global, and detailed placement)
design.writeDef("placed.def")
print("Saved placed.def")

# --- Insert Filler Cells ---
# Filler cells are inserted after detailed placement to fill any remaining empty spaces in the standard cell rows,
# ensuring power/ground rail continuity and a fixed-height row structure.
print("\n--- Inserting filler cells ---")
# Need site information to place fillers correctly within rows
site_for_fillers = None
rows = block.getRows()
if rows:
    site_for_fillers = rows[0].getSite()
elif site: # Use site found earlier if rows don't exist (less common after placement)
     site_for_fillers = site

if site_for_fillers:
    db = ord.get_db()
    filler_masters = list()
    # Search through library masters to find cells of type CORE_SPACER (typical filler cell type)
    for lib in db.getLibs():
        for master in lib.getMasters():
            if master.getType() == "CORE_SPACER":
                filler_masters.append(master)

    if len(filler_masters) == 0:
        print("Warning: No CORE_SPACER filler cells found in library! Skipping filler placement.")
    else:
        # Re-get opendp object as it might have been used previously
        opendp = design.getOpendp()
        # Remove any existing fillers before inserting new ones based on updated placement
        # This is important if the script is run multiple times or incrementally
        opendp.removeFillers()
        # Run the filler placement
        opendp.fillerPlacement(
            filler_masters = filler_masters, # List of standard cell masters to use as fillers
            prefix = "FILLCELL_", # Prefix to use for the instance names of inserted filler cells
            verbose = False # Set to True for detailed output about filler placement
        )
        print("Filler cell placement complete.")
else:
    print("Skipping filler cell placement: Site information not available.")

# Dump DEF file after filler placement (optional, good for debugging/visualization)
# design.writeDef("filled.def")
# print("Saved filled.def")


# --- 5. Clock Tree Synthesis (CTS) ---
print("\n--- 5. Performing Clock Tree Synthesis (CTS) ---")
cts = design.getTritonCts() # Get the TritonCTS object

# Specify the clock net(s) to synthesize the clock tree for.
# Use evalTclString to execute the TCL command as shown in examples.
if clock_net: # Ensure the clock_net object exists from step 1
    design.evalTclString(f"set cts_clocks [get_clocks {clock_name}]")
    print(f"Targeting clock '{clock_name}' for CTS.")
else:
    print(f"Warning: Clock net '{clock_name}' not found. CTS will not be performed on this clock.")


# Set the standard cell masters to be used as clock buffers (list, root, sink)
cts.setBufferList(cts_buffer_name) # List of all buffer types allowed
cts.setRootBuffer(cts_buffer_name) # Specific buffer type for the tree root
cts.setSinkBuffer(cts_buffer_name) # Specific buffer type for the tree sinks (endpoints)

# Set other CTS parameters if needed (e.g., target skew, target latency, wire segment unit)
# parms = cts.getParms()
# parms.setWireSegmentUnit(20) # Example: Set the unit length for wire segments in the tree

# Run the CTS algorithm to build the clock tree
cts.runTritonCts()
print("CTS complete.")

# Dump DEF file after CTS. This DEF includes the inserted clock buffers and clock network routing shapes.
design.writeDef("cts.def")
print("Saved cts.def")


# --- 6. Power Distribution Network (PDN) ---
print("\n--- 6. Building Power Distribution Network (PDN) ---")

# Mark power and ground nets as special nets. This prevents the signal router from trying to route these nets.
print("Marking power and ground nets as special...")
for net in block.getNets():
    # Check the signal type ('POWER' or 'GROUND') and mark the net as special
    if net.getSigType() == "POWER" or net.getSigType() == "GROUND":
        net.setSpecial()
print("Special nets marked.")

# Find the main VDD (power) and VSS (ground) nets in the block or create them if they don't exist.
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

if VDD_net is None:
    print("Creating VDD net...")
    VDD_net = odb.dbNet_create(block, "VDD") # Create a new net object
    VDD_net.setSigType("POWER") # Set its signal type to POWER
    VDD_net.setSpecial() # Mark it as special
    print("VDD net created.")

if VSS_net is None:
    print("Creating VSS net...")
    VSS_net = odb.dbNet_create(block, "VSS") # Create a new net object
    VSS_net.setSigType("GROUND") # Set its signal type to GROUND
    VSS_net.setSpecial() # Mark it as special
    print("VSS net created.")

# Globally connect standard cell VDD/VSS pins to the created global VDD/VSS nets.
# This ensures that all standard cell power and ground pins are tied to the global PDN.
print("Globally connecting standard cell power and ground pins...")
# Remove any existing global connects first to ensure clean setup if script is rerun
block.removeGlobalConnect("*", "*", "*") # Remove all existing global connect rules
# Add global connect rules: for all instances (*), connect pins matching "^VDD$" to VDD_net
block.addGlobalConnect(region = None, instPattern = "*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
# Add global connect rules: for all instances (*), connect pins matching "^VSS$" to VSS_net
block.addGlobalConnect(region = None, instPattern = "*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
block.globalConnect() # Apply the global connect rules
print("Global connect complete.")

# Get the PDN generator object
pdngen = design.getPdnGen()

# Set the core power domain. This defines the primary power and ground nets for the core area.
pdngen.setCoreDomain(power = VDD_net, switched_power = None, ground = VSS_net, secondary = [])
print("Core power domain set.")

# Find the core domain grid setup object(s). Usually, there's one associated with the Core domain.
domains = [pdngen.findDomain("Core")]
if not domains:
    print("Error: Core domain not found! Cannot proceed with PDN grid definition.")
else:
    # Create the main core grid structure definition for standard cells.
    # This defines the overall grid topology and which nets are used over the core area.
    pdngen.makeCoreGrid(
        domain = domains[0], # Associate this grid definition with the Core domain
        name = "top", # Assign a name to this core grid definition (used later to retrieve it)
        starts_with = pdn.GROUND, # Defines the starting net for strap/ring patterns (can be pdn.POWER or pdn.GRID)
        # Additional parameters can be configured, like pin_layers for connecting to specific pins.
    )
    print("Core grid structure defined.")

    # Find required metal layers by name for PDN construction.
    # Need to check if these layers exist in the technology LEF.
    m1 = tech.findLayer("metal1")
    m4 = tech.findLayer("metal4")
    m5 = tech.findLayer("metal5")
    m6 = tech.findLayer("metal6")
    m7 = tech.findLayer("metal7")
    m8 = tech.findLayer("metal8")

    # Check if all required layers for the specified PDN structure were found.
    required_layer_names = ["metal1", "metal4", "metal5", "metal6", "metal7", "metal8"]
    required_layers = [m1, m4, m5, m6, m7, m8]
    missing_layers = [name for layer, name in zip(required_layers, required_layer_names) if not layer]

    if missing_layers:
        print(f"Error: Missing required metal layers for PDN: {', '.join(missing_layers)}. Cannot proceed with PDN generation details.")
    else:
        # Get the core grid object(s) created by makeCoreGrid with the name "top"
        core_grid = pdngen.findGrid("top")

        # Create standard cell PDN structures (straps and followpins) associated with the core grid.
        if core_grid:
            for g in core_grid: # Iterate over grid objects found (usually one for the core domain)
                print("Creating standard cell PDN straps...")
                # M1 Followpin: Creates power/ground straps on M1 that "follow" the standard cell row power/ground pins.
                pdngen.makeFollowpin(
                    grid = g, # Associate followpins with this grid object
                    layer = m1, # The metal layer for followpins
                    width = design.micronToDBU(std_cell_m1_width_um), # Width of the followpin straps
                    extend = pdn.CORE # Extend followpins throughout the core area
                )

                # M4 Straps: Creates a pattern of power/ground straps on M4.
                # Orientation (horizontal/vertical) is determined by the layer's preferred direction.
                pdngen.makeStrap(
                    grid = g, # Associate straps with this grid object
                    layer = m4, # The metal layer for straps
                    width = design.micronToDBU(std_cell_m4_width_um), # Width of the straps
                    spacing = design.micronToDBU(std_cell_m4_spacing_um), # Spacing between straps
                    pitch = design.micronToDBU(std_cell_m4_pitch_um), # Pitch (center-to-center distance) of the straps
                    offset = design.micronToDBU(pdn_offset_um), # Offset from the starting edge of the pattern
                    number_of_straps = 0, # If 0, auto-calculates the number of straps based on pitch and area
                    snap = False, # Set to True to snap straps to the layer's grid or track grid
                    starts_with = pdn.GRID, # Defines where the strap pattern starts relative to the grid boundary
                    extend = pdn.CORE, # Extend straps across the core area
                    nets = [VDD_net, VSS_net] # List of nets carried by this strap pattern
                )

                # M7 Straps: Creates another pattern of power/ground straps on M7.
                pdngen.makeStrap(
                    grid = g,
                    layer = m7,
                    width = design.micronToDBU(std_cell_m7_width_um),
                    spacing = design.micronToDBU(std_cell_m7_spacing_um),
                    pitch = design.micronToDBU(std_cell_m7_pitch_um),
                    offset = design.micronToDBU(pdn_offset_um),
                    number_of_straps = 0,
                    snap = False,
                    starts_with = pdn.GRID,
                    extend = pdn.CORE,
                    nets = [VDD_net, VSS_net]
                )
                print("Standard cell PDN straps defined.")

                # Create power rings on M7 and M8 around the core boundary.
                # Rings provide a robust power/ground connection loop around the design.
                print("Creating power rings...")
                pdngen.makeRing(
                    grid = g, # Associate rings with the core grid object
                    layer0 = m7, # First layer for the ring
                    width0 = design.micronToDBU(ring_m7_width_um), # Width of M7 straps in the ring
                    spacing0 = design.micronToDBU(ring_m7_spacing_um), # Spacing between M7 straps in the ring
                    layer1 = m8, # Second layer for the ring
                    width1 = design.micronToDBU(ring_m8_width_um), # Width of M8 straps in the ring
                    spacing1 = design.micronToDBU(ring_m8_spacing_um), # Spacing between M8 straps in the ring
                    starts_with = pdn.GROUND, # Example: Defines the order of VSS/VDD straps in the ring
                    offset = [design.micronToDBU(pdn_offset_um)] * 4, # Offset from the boundary [Left, Bottom, Right, Top]
                    pad_offset = [design.micronToDBU(0)] * 4, # Offset for the area where pads can connect to the ring (usually 0)
                    extend = pdn.BOUNDARY, # Extend the ring to the die boundary
                    pad_pin_layers = [], # List of layers on pads that should connect to the ring (empty list if not connecting pads)
                    nets = [VDD_net, VSS_net] # Specify nets carried by the rings
                )
                print("Power rings defined.")

                # Create via connections between PDN layers.
                # Vias connect straps/rings on different layers to form a continuous grid.
                print("Creating via connections for standard cell grid and rings...")
                via_cut_pitch_dbu_x = design.micronToDBU(via_cut_pitch_um)
                via_cut_pitch_dbu_y = design.micronToDBU(via_cut_pitch_um)

                # Connect M1 (followpins) to M4 (straps)
                pdngen.makeConnect(
                    grid = g, layer0 = m1, layer1 = m4, # Layers to connect
                    cut_pitch_x = via_cut_pitch_dbu_x, cut_pitch_y = via_cut_pitch_dbu_y, # Pitch for generating via cuts
                    vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = {}, dont_use_vias = "" # Other parameters (usually default)
                )

                # Connect M4 (straps) to M7 (straps/rings)
                pdngen.makeConnect(
                    grid = g, layer0 = m4, layer1 = m7,
                    cut_pitch_x = via_cut_pitch_dbu_x, cut_pitch_y = via_cut_pitch_dbu_y,
                    vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = {}, dont_use_vias = ""
                )

                # Connect M7 (straps/rings) to M8 (rings)
                pdngen.makeConnect(
                    grid = g, layer0 = m7, layer1 = m8,
                    cut_pitch_x = via_cut_pitch_dbu_x, cut_pitch_y = via_cut_pitch_dbu_y,
                    vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = {}, dont_use_vias = ""
                )
                print("Standard cell grid and ring via connections defined.")
        else:
            print("Warning: Core grid 'top' not found. Skipping standard cell PDN generation details.")


        # Create power grid structures specifically for macro blocks (if macros exist)
        # These grids are typically placed within the macro's boundary and connected to the main core grid.
        if macros:
            print("Creating macro PDN grids and straps...")
            macro_halo_dbu = design.micronToDBU(macro_halo_um)
            # Halo is defined as a list [left, bottom, right, top] relative to the instance boundary
            halo_list_dbu = [macro_halo_dbu] * 4

            for i, macro_inst in enumerate(macros):
                print(f"  Creating PDN for macro instance: {macro_inst.getName()}")
                # Create a separate instance grid definition for each macro within the Core domain
                if domains: # Ensure Core domain exists
                    pdngen.makeInstanceGrid(
                        domain = domains[0], # Associate this macro grid definition with the Core domain
                        name = f"macro_grid_{i}", # Assign a unique name for this macro's grid
                        starts_with = pdn.GROUND, # Example start (can be pdn.POWER or pdn.GRID)
                        inst = macro_inst, # Associate this grid definition with the specific macro instance
                        halo = halo_list_dbu, # Halo size around the macro instance boundary where PDN structures won't be placed
                        pg_pins_to_boundary = True, # Connect macro's internal power/ground pins to the instance grid boundary
                        default_grid = False, # This is an instance-specific grid, not the default core grid
                        # Other parameters left as default
                    )

                    # Get the created instance grid object for the current macro
                    macro_instance_grid = pdngen.findGrid(f"macro_grid_{i}")
                    if macro_instance_grid:
                        for mg in macro_instance_grid: # Iterate over macro grid objects (usually one per instance grid definition)
                            # Create power straps on M5 within the macro instance area
                            pdngen.makeStrap(
                                grid = mg, # Associate straps with this macro instance grid object
                                layer = m5, # The metal layer for straps
                                width = design.micronToDBU(macro_m5_width_um),
                                spacing = design.micronToDBU(macro_m5_spacing_um),
                                pitch = design.micronToDBU(macro_m5_pitch_um),
                                offset = design.micronToDBU(pdn_offset_um),
                                number_of_straps = 0,
                                snap = True, # Often snaps to internal macro grid or pins
                                starts_with = pdn.GRID,
                                extend = pdn.CORE, # Extend across the macro's instance area boundary
                                nets = [VDD_net, VSS_net] # Specify nets carried by the macro straps
                            )
                            # Create power straps on M6 within the macro instance area
                            pdngen.makeStrap(
                                grid = mg,
                                layer = m6,
                                width = design.micronToDBU(macro_m6_width_um),
                                spacing = design.micronToDBU(macro_m6_spacing_um),
                                pitch = design.micronToDBU(macro_m6_pitch_um),
                                offset = design.micronToDBU(pdn_offset_um),
                                number_of_straps = 0,
                                snap = True,
                                starts_with = pdn.GRID,
                                extend = pdn.CORE,
                                nets = [VDD_net, VSS_net]
                            )
                            print(f"  Macro {i} straps defined.")

                            # Create via connections for macro grid layers and connections to the core grid
                            print(f"  Creating via connections for macro {i} grid...")
                            # Connect M4 (part of core grid) to M5 (part of macro grid) - This bridges the macro grid to the core grid
                            pdngen.makeConnect(
                                grid = mg, layer0 = m4, layer1 = m5, # Connecting core grid layer M4 to macro grid layer M5
                                cut_pitch_x = via_cut_pitch_dbu_x, cut_pitch_y = via_cut_pitch_dbu_y,
                                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = {}, dont_use_vias = ""
                            )
                             # Connect M5 to M6 (macro grid layers)
                            pdngen.makeConnect(
                                grid = mg, layer0 = m5, layer1 = m6, # Connecting macro grid layer M5 to macro grid layer M6
                                cut_pitch_x = via_cut_pitch_dbu_x, cut_pitch_y = via_cut_pitch_dbu_y,
                                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = {}, dont_use_vias = ""
                            )
                            # Connect M6 (part of macro grid) to M7 (part of core grid) - This bridges the macro grid to the core grid
                            pdngen.makeConnect(
                                grid = mg, layer0 = m6, layer1 = m7, # Connecting macro grid layer M6 to core grid layer M7
                                cut_pitch_x = via_cut_pitch_dbu_x, cut_pitch_y = via_cut_pitch_dbu_y,
                                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = {}, dont_use_vias = ""
                            )
                            print(f"  Macro {i} via connections defined.")
                    else:
                        print(f"Warning: Instance grid '{f'macro_grid_{i}'}' not found for macro {macro_inst.getName()}. Skipping macro PDN generation for this instance.")
                else:
                    print("Warning: Core domain not found. Cannot create macro instance grids.")
        else:
            print("No macros found. Skipping macro PDN generation.")

    # Build the power grid structures and write them to the design database.
    # This generates the actual metal shapes and vias based on the definitions.
    print("Building and writing PDN to DB...")
    pdngen.checkSetup() # Verify the PDN setup configuration for potential issues
    pdngen.buildGrids(False) # Build the geometry of the power grid structures (False disables creating obstructions)
    pdngen.writeToDb(True) # Write the created metal shapes and vias to the design database (True commits the changes)
    pdngen.resetShapes() # Reset temporary shapes used during generation
    print("PDN generation complete.")

    # Dump DEF file after PDN generation to visualize the power grid structures.
    design.writeDef("pdn.def")
    print("Saved pdn.def")


# --- 7. Routing ---
print("\n--- 7. Performing routing ---")

# Find the minimum and maximum routing layers by name from the technology
min_route_layer_obj = tech.findLayer(global_router_min_layer_name)
max_route_layer_obj = tech.findLayer(global_router_max_layer_name)

if not min_route_layer_obj or not max_route_layer_obj:
    print(f"Error: Routing layers '{global_router_min_layer_name}' or '{global_router_max_layer_name}' not found! Cannot proceed with routing.")
else:
    # Get the integer routing levels for the found layers
    min_route_level = min_route_layer_obj.getRoutingLevel()
    max_route_level = max_route_layer_obj.getRoutingLevel()

    # Global Routing: Plans the general paths for nets across the design area.
    print("Performing global routing...")
    grt = design.getGlobalRouter() # Get the GlobalRouter object
    # Set the range of routing layers allowed for signal nets
    grt.setMinRoutingLayer(min_route_level)
    grt.setMaxRoutingLayer(max_route_level)
    # Set the range of routing layers allowed for clock nets (can be same or different from signal layers)
    grt.setMinLayerForClock(min_route_level)
    grt.setMaxLayerForClock(max_route_level)
    grt.setAdjustment(global_router_adj) # Set the congestion adjustment factor (0.0 - 1.0; higher means more spacing)
    grt.setVerbose(True) # Enable verbose output for routing progress

    # The parameter for Global Router iterations (20 requested in prompt) was not found in the provided API examples.
    # Proceeding using the default number of iterations or flow steps implemented within the global router.
    # If specific control over GR iterations is needed, consult OpenROAD documentation for alternative APIs or TCL commands.

    grt.globalRoute(True) # Run global routing. 'True' often indicates to generate routing guides for the detailed router.
    print("Global routing complete.")

    # Detailed Routing: Lays out actual metal wires and vias following the global routing guides,
    # respecting design rules (DRC) and manufacturing constraints.
    print("Performing detailed routing...")
    drter = design.getTritonRoute() # Get the TritonRoute detailed router object
    params = drt.ParamStruct() # Create a parameter structure to configure the detailed router

    # Configure detailed router parameters. Note: These often use layer *names*.
    params.bottomRoutingLayer = detailed_router_min_layer_name # Lowest layer for detailed routing
    params.topRoutingLayer = detailed_router_max_layer_name # Highest layer for detailed routing
    params.verbose = 1 # Set verbosity level (1 is typically informative)
    params.cleanPatches = True # Enable cleaning up small metal patches after routing
    params.doPa = True # Enable pin access routing (connecting cell pins to routing tracks)
    params.singleStepDR = False # Set to False to run the complete DR flow (True runs one iteration)
    # params.drouteEndIter = 1 # Optional: Limit the number of detailed routing iterations

    drter.setParams(params) # Apply the configured parameters to the router instance
    drter.main() # Run the detailed routing process
    print("Detailed routing complete.")
else:
    print("Skipping routing due to missing routing layers.")


# Dump the final DEF file after routing.
# This DEF includes all placed cells, the PDN, CTS trees, and signal routing.
design.writeDef("routed.def")
print("Saved routed.def")

print("\n--- Physical Design Flow Complete ---")

# Optional: Write the final Verilog netlist.
# This netlist may include buffers inserted during CTS and reflect the final logical structure.
# design.evalTclString("write_verilog final.v")
# print("Saved final.v")