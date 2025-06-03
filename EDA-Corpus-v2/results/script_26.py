# Import necessary libraries
import odb
import pdn
import drt
import openroad as ord
import os

# Get the current design block
block = design.getBlock()
tech = design.getTech().getDB().getTech()

# 1. Clock Setup

# Clock parameters from user request
clock_period_ns = 50
clock_port_name = "clk_i"
clock_net_name = "core_clock"

print(f"Setting up clock {clock_net_name} on port {clock_port_name} with period {clock_period_ns} ns...")

# Create clock signal on the specified port with the given period
# OpenROAD Tcl command for creating a clock
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_net_name}")
# Propagate the created clock signal throughout the design
# OpenROAD Tcl command to set propagated clock
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_net_name}}}]")

# Set unit resistance and capacitance values for clock and signal nets
resistance = 0.0435
capacitance = 0.0817
print(f"Setting wire RC values: Resistance={resistance}, Capacitance={capacitance}...")
# OpenROAD Tcl command to set wire RC values for clock nets
design.evalTclString(f"set_wire_rc -clock -resistance {resistance} -capacitance {capacitance}")
# OpenROAD Tcl command to set wire RC values for signal nets
design.evalTclString(f"set_wire_rc -signal -resistance {resistance} -capacitance {capacitance}")


# 2. Floorplan

print("Performing floorplanning...")
floorplan = design.getFloorplan()

# Define die area bounding box coordinates in microns
die_lx_um, die_ly_um = 0, 0
die_ux_um, die_uy_um = 70, 70
# Convert microns to Database Units (DBU)
die_area = odb.Rect(design.micronToDBU(die_lx_um), design.micronToDBU(die_ly_um),
                    design.micronToDBU(die_ux_um), design.micronToDBU(die_uy_um))

# Define core area bounding box coordinates in microns
core_lx_um, core_ly_um = 6, 6
core_ux_um, core_uy_um = 64, 64
# Convert microns to Database Units (DBU)
core_area = odb.Rect(design.micronToDBU(core_lx_um), design.micronToDBU(core_ly_um),
                     design.micronToDBU(core_ux_um), design.micronToDBU(core_uy_um))

# Find a placement site from the technology library
# It's common to get the site from an existing row if available, or search tech lib
site = None
rows = block.getRows()
if len(rows) > 0:
    # Get site from the first row
    site = rows[0].getSite()
else:
    # If no rows, search the technology library for a CORE site
    for s in tech.getSites():
        if s.getClass() == "CORE":
             site = s
             break

if site is None:
    # Raise an error if no placement site could be found
    raise Exception("Could not find a core placement site in the technology library or existing rows.")

# Initialize floorplan with the defined die area, core area, and placement site
floorplan.initFloorplan(die_area, core_area, site)

# Create placement tracks within the core area based on the site definition
floorplan.makeTracks()

# Save DEF file after floorplanning
design.writeDef("floorplan.def")


# 3. Placement

print("Performing placement...")

# Identify macro blocks in the design
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

# Place macro blocks if they exist in the design
if len(macros) > 0:
    print(f"Found {len(macros)} macros. Running macro placement...")
    mpl = design.getMacroPlacer()

    # Define macro placement parameters from user request
    macro_fence_lx_um, macro_fence_ly_um = 32, 32 # Bottom-left corner of macro placement bounding box in microns
    macro_fence_ux_um, macro_fence_uy_um = 55, 60 # Top-right corner of macro placement bounding box in microns
    macro_min_dist_um = 5 # Minimum distance between macros in microns
    macro_halo_um = 5 # Halo region around each macro in microns

    # Macro placer parameters dictionary
    # Using a dictionary for clarity and to easily pass parameters
    mpl_params = {
        'num_threads': 64, # Number of threads for parallel processing
        # Bounding box (fence region) for macro placement
        'fence_lx': macro_fence_lx_um,
        'fence_ly': macro_fence_ly_um,
        'fence_ux': macro_fence_ux_um,
        'fence_uy': macro_fence_uy_um,
        'fence_weight': 10.0, # Weight for fence constraint
        # Minimum distance requirement between macro instances
        'min_macro_macro_dist': macro_min_dist_um,
        # Halo size around each macro instance (exclusion zone for standard cells)
        'halo_width': macro_halo_um,
        'halo_height': macro_halo_um,
        # Other placement parameters (can be tuned)
        'target_util': 0.25, # Target utilization for standard cells
        'target_dead_space': 0.05, # Target dead space
        'area_weight': 0.1,
        'outline_weight': 100.0,
        'wirelength_weight': 100.0,
        'guidance_weight': 10.0,
        'boundary_weight': 50.0,
        'notch_weight': 10.0,
        'macro_blockage_weight': 10.0,
        'pin_access_th': 0.0,
        'min_ar': 0.33, # Minimum aspect ratio
        'snap_layer': 1, # Snap macro origins to Metal1 tracks (common)
        'bus_planning_flag': False, # Disable bus planning
        'report_directory': "" # Directory for reports (empty for no reports)
    }

    # Run macro placement with the specified parameters
    mpl.place(**mpl_params)

    # Save DEF file after macro placement
    design.writeDef("macro_placement.def")
else:
    print("No macros found. Skipping macro placement.")


# Configure and run global placement for standard cells
print("Running global placement...")
gpl = design.getReplace()
# Disable timing-driven placement (focus on density/routability first)
gpl.setTimingDrivenMode(False)
# Enable routability-driven placement to reduce congestion
gpl.setRoutabilityDrivenMode(True)
# Enable uniform target density across the core area
gpl.setUniformTargetDensityMode(True)

# Run the initial placement stage
gpl.doInitialPlace(threads = 4) # Use 4 threads (example)
# Run the Nesterov-based placement stage
gpl.doNesterovPlace(threads = 4) # Use 4 threads (example)
# Reset the placer state
gpl.reset()


# Configure and run initial detailed placement
print("Running initial detailed placement...")
opendp = design.getOpendp()
# Maximum displacement allowed for cells in DBU
# User requested 0 um displacement in x and y, convert to DBU
max_disp_x_um = 0
max_disp_y_um = 0
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

# Remove any previously placed filler cells (if any) before running detailed placement
# This is often needed to allow cells to move freely
opendp.removeFillers()

# Perform detailed placement
# Parameters: max_disp_x, max_disp_y, cell_name_pattern (empty string for all), verbose
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

# Save DEF file after initial detailed placement
design.writeDef("initial_placement.def")


# 4. Clock Tree Synthesis (CTS)

print("Running clock tree synthesis...")
cts = design.getTritonCts()

# Set the list of available clock buffer library cells
cts.setBufferList("BUF_X3")
# Set the cell to use for the clock root
cts.setRootBuffer("BUF_X3")
# Set the cell to use for clock sinks (endpoints)
cts.setSinkBuffer("BUF_X3")
# Specify the clock net to build the tree for
# setClockNets returns 0 on success, 1 if net not found
if cts.setClockNets(clock_net_name) != 0:
     print(f"Warning: Clock net '{clock_net_name}' not found for CTS.")

# Run the clock tree synthesis process
cts.runTritonCts()

# Save DEF file after CTS
design.writeDef("cts.def")


# 5. Detailed Placement (Post-CTS)

print("Running final detailed placement after CTS...")
# CTS might slightly move instances, so another detailed placement run is common
# User requested 0 um displacement in x and y again for this stage
max_disp_x_dbu = design.micronToDBU(0)
max_disp_y_dbu = design.micronToDBU(0)

# Remove fillers again before detailed placement if they were inserted after initial DP
opendp.removeFillers()

# Perform detailed placement again
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

# Save DEF file after final detailed placement
design.writeDef("final_placement.def")


# 6. Power Delivery Network (PDN)

print("Setting up power delivery network...")
pdngen = design.getPdnGen()

# Find or create Power and Ground nets
# These should typically exist after reading the Verilog netlist
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

# Create VDD/VSS nets if they don't exist (robustness)
if VDD_net is None:
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSigType("POWER") # Set signal type to POWER
    VDD_net.setSpecial() # Mark as a special net (not for standard routing)
    print("Created VDD net.")
if VSS_net is None:
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSigType("GROUND") # Set signal type to GROUND
    VSS_net.setSpecial() # Mark as a special net
    print("Created VSS net.")

# Connect standard cell power/ground pins to the global nets
# Connect all instance VDD pins to the global VDD net
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
# Connect all instance VSS pins to the global VSS net
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
# Add common variations of PG pin names just in case (from Example 1)
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDPE$", net = VDD_net, do_connect = True)
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDCE$", net = VDD_net, do_connect = True)
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSSE$", net = VSS_net, do_connect = True)

# Apply the global connections to the design
block.globalConnect()
print("Connected standard cell power/ground pins to global nets.")

# Set the core power domain for the PDN generator
# Assign the primary power and ground nets to the core domain
pdngen.setCoreDomain(power = VDD_net, switched_power = None, ground = VSS_net, secondary = [])
print("Set core power domain.")

# Define power grid and ring parameters in microns and convert to DBU
m1_width_um = 0.07
m4_width_um = 1.2
m4_spacing_um = 1.2
m4_pitch_um = 6
m7_width_um = 1.4 # User asked for grid on M7 with 1.4/1.4/10.8
m7_spacing_um = 1.4
m7_pitch_um = 10.8
m8_width_um = 1.4 # User asked for grid on M8 with 1.4/1.4/10.8
m8_spacing_um = 1.4
m8_pitch_um = 10.8

m5_width_um = 1.2
m5_spacing_um = 1.2
m5_pitch_um = 6
m6_width_um = 1.2
m6_spacing_um = 1.2
m6_pitch_um = 6

ring_m7_width_um = 4 # User asked for ring on M7 with 4/4
ring_m7_spacing_um = 4
ring_m8_width_um = 4 # User asked for ring on M8 with 4/4
ring_m8_spacing_um = 4

via_pitch_um = 2 # User asked for via pitch between parallel grids

# Convert parameters to DBU (Database Units)
m1_width_dbu = design.micronToDBU(m1_width_um)
m4_width_dbu = design.micronToDBU(m4_width_um)
m4_spacing_dbu = design.micronToDBU(m4_spacing_um)
m4_pitch_dbu = design.micronToDBU(m4_pitch_um)
m7_width_dbu = design.micronToDBU(m7_width_um)
m7_spacing_dbu = design.micronToDBU(m7_spacing_um)
m7_pitch_dbu = design.micronToDBU(m7_pitch_um)
m8_width_dbu = design.micronToDBU(m8_width_um)
m8_spacing_dbu = design.micronToDBU(m8_spacing_um)
m8_pitch_dbu = design.micronToDBU(m8_pitch_um)

m5_width_dbu = design.micronToDBU(m5_width_um)
m5_spacing_dbu = design.micronToDBU(m5_spacing_um)
m5_pitch_dbu = design.micronToDBU(m5_pitch_um)
m6_width_dbu = design.micronToDBU(m6_width_um)
m6_spacing_dbu = design.micronToDBU(m6_spacing_um)
m6_pitch_dbu = design.micronToDBU(m6_pitch_um)

ring_m7_width_dbu = design.micronToDBU(ring_m7_width_um)
ring_m7_spacing_dbu = design.micronToDBU(ring_m7_spacing_um)
ring_m8_width_dbu = design.micronToDBU(ring_m8_width_um)
ring_m8_spacing_dbu = design.micronToDBU(ring_m8_spacing_dbu)

via_pitch_dbu = design.micronToDBU(via_pitch_um)

# Get metal layers by name from the technology library
m1 = tech.findLayer("metal1")
m4 = tech.findLayer("metal4")
m5 = tech.findLayer("metal5")
m6 = tech.findLayer("metal6")
m7 = tech.findLayer("metal7")
m8 = tech.findLayer("metal8")

# Ensure required layers are found
if not all([m1, m4, m5, m6, m7, m8]):
    missing = [l for l, name in zip([m1, m4, m5, m6, m7, m8], ["metal1", "metal4", "metal5", "metal6", "metal7", "metal8"]) if l is None]
    raise Exception(f"Could not find required metal layers: {', '.join(missing)}")


# Create the main core grid structure (for standard cells and core rings)
# This defines the domain and nets covered by this grid structure
domains = [pdngen.findDomain("Core")] # Assuming core domain was set up
halo_dbu = [0] * 4 # No halo exclusion for the main core grid definition itself
for domain in domains:
    # Create the core grid object
    pdngen.makeCoreGrid(domain = domain,
                        name = "core_grid",
                        starts_with = pdn.GROUND, # Define the starting net for the strap pattern
                        pin_layers = [], # Optional: Layers for pin connections
                        generate_obstructions = [], # Optional: Layers to generate obstructions on
                        powercell = None,
                        powercontrol = None,
                        powercontrolnetwork = "STAR") # Star or Ring connection topology

# Find the core grid object that was created
core_grid = pdngen.findGrid("core_grid")[0]

# Add standard cell power stripes (followpin on M1)
# These straps follow the standard cell power/ground pin patterns on the lowest layer
pdngen.makeFollowpin(grid = core_grid,
                     layer = m1, # Use metal1 for followpin straps
                     width = m1_width_dbu, # Set the width
                     extend = pdn.CORE) # Extend the straps to the core boundary
print(f"Added M1 followpin straps with width {m1_width_um} um.")

# Add standard cell power straps (M4)
pdngen.makeStrap(grid = core_grid,
                 layer = m4, # Use metal4 for standard cell grid straps
                 width = m4_width_dbu, # Set the width
                 spacing = m4_spacing_dbu, # Set the spacing between straps of the same net
                 pitch = m4_pitch_dbu, # Set the pitch (distance between centers of adjacent VDD/VSS straps)
                 offset = design.micronToDBU(0), # User requested offset 0
                 number_of_straps = 0, # Auto-calculate number of straps based on pitch/area
                 snap = False, # Do not snap to routing grid (common for standard cell power rails)
                 starts_with = pdn.GRID, # Start pattern based on the grid definition (e.g., VSS VDD VSS VDD...)
                 extend = pdn.CORE, # Extend the straps within the core area
                 nets = []) # Use the nets defined in the grid (VDD/VSS)
print(f"Added M4 straps with width {m4_width_um} um, spacing {m4_spacing_um} um, pitch {m4_pitch_um} um.")

# Add core power rings (M7 and M8) around the core boundary
# Use the makeRing function for this specific topology
pdngen.makeRing(grid = core_grid, # Associate rings with the core grid
                layer0 = m7, # Inner ring layer (e.g., vertical)
                width0 = ring_m7_width_dbu, # Width for layer0
                spacing0 = ring_m7_spacing_dbu, # Spacing for layer0
                layer1 = m8, # Outer ring layer (e.g., horizontal)
                width1 = ring_m8_width_dbu, # Width for layer1
                spacing1 = ring_m8_spacing_dbu, # Spacing for layer1
                starts_with = pdn.POWER, # Define the starting net for the ring pattern (e.g., VDD VSS VDD VSS...)
                offset = [design.micronToDBU(0)]*4, # Offset from the boundary [left, bottom, right, top]
                pad_offset = [design.micronToDBU(0)]*4, # Offset for connection to pads (if any)
                extend = True, # Extend rings to the boundary of the core grid
                pad_pin_layers = [], # Layers to connect to pads (optional)
                nets = []) # Use the nets defined in the grid (VDD/VSS)
print(f"Added M7/M8 rings with widths {ring_m7_width_um}/{ring_m8_width_um} um and spacings {ring_m7_spacing_um}/{ring_m8_spacing_um} um.")

# Add core power straps (M7 and M8 grids) - If needed in addition to rings
# This could mean a more dense grid *within* the core using these layers
# Based on the request, add straps with the specified pitch/spacing
pdngen.makeStrap(grid = core_grid,
                 layer = m7, # Use metal7 for core grid straps
                 width = m7_width_dbu,
                 spacing = m7_spacing_dbu,
                 pitch = m7_pitch_dbu,
                 offset = design.micronToDBU(0),
                 number_of_straps = 0,
                 snap = False,
                 starts_with = pdn.GRID,
                 extend = pdn.CORE,
                 nets = [])
print(f"Added M7 straps with width {m7_width_um} um, spacing {m7_spacing_um} um, pitch {m7_pitch_um} um.")

pdngen.makeStrap(grid = core_grid,
                 layer = m8, # Use metal8 for core grid straps
                 width = m8_width_dbu,
                 spacing = m8_spacing_dbu,
                 pitch = m8_pitch_dbu,
                 offset = design.micronToDBU(0),
                 number_of_straps = 0,
                 snap = False,
                 starts_with = pdn.GRID,
                 extend = pdn.CORE, # Extend within the core area
                 nets = [])
print(f"Added M8 straps with width {m8_width_um} um, spacing {m8_spacing_um} um, pitch {m8_pitch_um} um.")


# Create power grid for macro blocks (if any exist)
if len(macros) > 0:
    print("Setting up macro power grids...")
    macro_halo_dbu = [design.micronToDBU(macro_halo_um)] * 4 # Use the same halo as placement for PDN exclusion
    for i, macro_inst in enumerate(macros):
        # Create an instance grid associated with each macro
        for domain in domains: # Assuming macros are part of the core domain
            pdngen.makeInstanceGrid(domain = domain,
                                    name = f"macro_grid_{i}", # Unique name for each macro grid
                                    starts_with = pdn.GROUND, # Strap pattern starts with Ground
                                    inst = macro_inst, # Associate grid with this instance
                                    halo = macro_halo_dbu, # Apply halo exclusion around the macro for standard cell PDN
                                    pg_pins_to_boundary = True, # Connect macro PG pins to the instance grid boundary
                                    default_grid = False, # This is not the default grid
                                    generate_obstructions = [],
                                    is_bump = False) # Not a bump grid

        # Find the instance grid object for this macro
        macro_inst_grid = pdngen.findGrid(f"macro_grid_{i}")[0]

        # Add macro power straps (M5 and M6)
        pdngen.makeStrap(grid = macro_inst_grid,
                         layer = m5, # Use metal5 for macro grid straps
                         width = m5_width_dbu,
                         spacing = m5_spacing_dbu,
                         pitch = m5_pitch_dbu,
                         offset = design.micronToDBU(0),
                         number_of_straps = 0,
                         snap = True, # Snap macro grid straps to routing grid
                         starts_with = pdn.GRID,
                         extend = pdn.CORE, # Extend straps within the instance grid's boundary
                         nets = [])
        print(f"  Macro {macro_inst.getName()}: Added M5 straps w={m5_width_um}, s={m5_spacing_um}, p={m5_pitch_um} um.")

        pdngen.makeStrap(grid = macro_inst_grid,
                         layer = m6, # Use metal6 for macro grid straps
                         width = m6_width_dbu,
                         spacing = m6_spacing_dbu,
                         pitch = m6_pitch_dbu,
                         offset = design.micronToDBU(0),
                         number_of_straps = 0,
                         snap = True,
                         starts_with = pdn.GRID,
                         extend = pdn.CORE, # Extend straps within the instance grid's boundary
                         nets = [])
        print(f"  Macro {macro_inst.getName()}: Added M6 straps w={m6_width_um}, s={m6_spacing_um}, p={m6_pitch_um} um.")

        # Create via connections within the macro grid and to core grid layers
        # Connections from core grid M4 to macro grid M5
        pdngen.makeConnect(grid = macro_inst_grid,
                           layer0 = m4, layer1 = m5,
                           cut_pitch_x = via_pitch_dbu, # Via pitch in X (for vertical connections)
                           cut_pitch_y = via_pitch_dbu, # Via pitch in Y (for horizontal connections)
                           vias = [], techvias = [], max_rows = 0, max_columns = 0,
                           ongrid = [], split_cuts = {}, dont_use_vias = "")
        # Connections within macro grid M5 to M6
        pdngen.makeConnect(grid = macro_inst_grid,
                           layer0 = m5, layer1 = m6,
                           cut_pitch_x = via_pitch_dbu,
                           cut_pitch_y = via_pitch_dbu,
                           vias = [], techvias = [], max_rows = 0, max_columns = 0,
                           ongrid = [], split_cuts = {}, dont_use_vias = "")
        # Connections from macro grid M6 to core grid M7
        pdngen.makeConnect(grid = macro_inst_grid,
                           layer0 = m6, layer1 = m7,
                           cut_pitch_x = via_pitch_dbu,
                           cut_pitch_y = via_pitch_dbu,
                           vias = [], techvias = [], max_rows = 0, max_columns = 0,
                           ongrid = [], split_cuts = {}, dont_use_vias = "")
    print("Finished setting up macro power grids.")


# Create via connections within the core grid between layers
# M1 (followpin) to M4 (straps)
pdngen.makeConnect(grid = core_grid,
                   layer0 = m1, layer1 = m4,
                   cut_pitch_x = via_pitch_dbu,
                   cut_pitch_y = via_pitch_dbu,
                   vias = [], techvias = [], max_rows = 0, max_columns = 0,
                   ongrid = [], split_cuts = {}, dont_use_vias = "")
print(f"Added vias between M1 and M4 with {via_pitch_um} um pitch.")

# M4 (straps) to M7 (straps/rings)
pdngen.makeConnect(grid = core_grid,
                   layer0 = m4, layer1 = m7,
                   cut_pitch_x = via_pitch_dbu,
                   cut_pitch_y = via_pitch_dbu,
                   vias = [], techvias = [], max_rows = 0, max_columns = 0,
                   ongrid = [], split_cuts = {}, dont_use_vias = "")
print(f"Added vias between M4 and M7 with {via_pitch_um} um pitch.")

# M7 (straps/rings) to M8 (straps/rings)
pdngen.makeConnect(grid = core_grid,
                   layer0 = m7, layer1 = m8,
                   cut_pitch_x = via_pitch_dbu,
                   cut_pitch_y = via_pitch_dbu,
                   vias = [], techvias = [], max_rows = 0, max_columns = 0,
                   ongrid = [], split_cuts = {}, dont_use_vias = "")
print(f"Added vias between M7 and M8 with {via_pitch_um} um pitch.")


# Generate the final power delivery network based on the defined structures
print("Generating power grid...")
pdngen.checkSetup() # Verify the PDN setup configuration
pdngen.buildGrids(False) # Build the actual geometry of the grids and vias in memory
pdngen.writeToDb(True) # Write the generated PDN shapes to the design database
pdngen.resetShapes() # Reset temporary shapes used during generation

# Save DEF file after PDN creation
design.writeDef("pdn.def")
print("Power grid generation complete.")

# Optional: Insert filler cells after PDN and before routing to fill gaps and tie-off PG pins
# This step is typically done after detailed placement and before routing.
import openroad as ord
db = ord.get_db()
filler_masters = list()
filler_cells_prefix = "FILLCELL_"
# Find CORE_SPACER type masters in the libraries
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

if len(filler_masters) == 0:
    print("No filler cells (CORE_SPACER) found in libraries. Skipping filler placement.")
else:
    print("Inserting filler cells...")
    # Perform filler cell placement in empty spaces within the core area
    design.getOpendp().fillerPlacement(filler_masters = filler_masters,
                                     prefix = filler_cells_prefix,
                                     verbose = False)
    # Save DEF after filler placement
    design.writeDef("placement_with_fillers.def")
    print("Filler cell placement complete.")


# 7. Analysis

# Perform IR drop analysis on M1 nodes of VDD net
print("Performing IR drop analysis on M1 VDD nodes...")
ir_drop_report_file = "ir_drop_m1_vdd.rpt"
# Using evalTclString to call the analyze_power_grid command (Volare tool)
# Ensure timing libraries (.lib) and parasitics (SPEF/DSPF) are loaded before this for accurate analysis
# The command parameters specify the voltage source, output report file, target net, and target layer
design.evalTclString(f"analyze_power_grid -voltage_source VDD -ir_drop_report {ir_drop_report_file} -net_name VDD -power_layer metal1")
print(f"IR drop report saved to {ir_drop_report_file}")

# Report power consumption
print("Reporting power (switching, leakage, internal, total)...")
# Using evalTclString to call the report_power command (OpenSTA tool)
# Requires timing libraries (.lib) and switching activity information (e.g., from gate-level simulation)
power_report_file = "power_report.rpt"
# The report_power command generates a power breakdown
design.evalTclString(f"report_power -outfile {power_report_file}")
print(f"Power report saved to {power_report_file}")


# 8. Routing

# Configure and run global routing
print("Running global routing...")
grt = design.getGlobalRouter()

# Define the minimum and maximum routing layers by name
min_route_layer_name = "metal1"
max_route_layer_name = "metal6"
min_route_layer = tech.findLayer(min_route_layer_name)
max_route_layer = tech.findLayer(max_route_layer_name)

# Check if the specified layers exist
if min_route_layer is None:
    raise Exception(f"Could not find routing layer {min_route_layer_name} in technology database.")
if max_route_layer is None:
     raise Exception(f"Could not find routing layer {max_route_layer_name} in technology database.")

# Get the routing levels (index) for the layers
min_route_level = min_route_layer.getRoutingLevel()
max_route_level = max_route_layer.getRoutingLevel()

# Set the minimum and maximum routing layers for signal nets
grt.setMinRoutingLayer(min_route_level)
grt.setMaxRoutingLayer(max_route_level)
# Use the same layer range for clock nets
grt.setMinLayerForClock(min_route_level)
grt.setMaxLayerForClock(max_route_level)

# Set global router adjustments (e.g., congestion map adjustments)
grt.setAdjustment(0.5) # Common adjustment value (0.0 to 1.0)
grt.setVerbose(True) # Enable verbose output

# Run global route
# The `globalRoute(True)` call enables the iterative routing process.
# While the user mentioned 20 iterations, the Python API doesn't directly control this count;
# it's managed internally by the tool's algorithm or Tcl variables not exposed here.
grt.globalRoute(True) # Run iterative global routing

# Save DEF file after global routing
design.writeDef("global_route.def")
print("Global routing complete.")


# Configure and run detailed routing
print("Running detailed routing...")
drter = design.getTritonRoute()
params = drt.ParamStruct()

# Set the minimum and maximum routing layers for detailed routing by name
params.bottomRoutingLayer = min_route_layer_name
params.topRoutingLayer = max_route_layer_name

# Set other detailed routing parameters
params.enableViaGen = True # Enable automatic via generation
params.drouteEndIter = 1 # Number of detailed routing iterations (1 is usually sufficient)
params.verbose = 1 # Set verbosity level (0: quiet, 1: normal, 2: verbose)
params.cleanPatches = True # Clean up DRC violations using patching
params.doPa = True # Perform pin access and post-route optimization
params.singleStepDR = False # Run detailed route in a single pass (can be False for multi-step)

# Optional: Specify output report files
# params.outputMazeFile = "droute_maze.rpt"
# params.outputDrcFile = "droute_drc.rpt"
# params.outputCmapFile = "droute_cmap.rpt"
# params.outputGuideCoverageFile = "droute_guide_coverage.rpt"

# Set the parameters for the detailed router
drter.setParams(params)

# Run detailed route
drter.main()

# Save DEF file after detailed routing
design.writeDef("detailed_route.def")
print("Detailed routing complete.")


# 9. Final Output

# Write the final DEF file containing the complete physical design
print("Writing final DEF file...")
design.writeDef("final.def")

# Write the final Verilog netlist (post-layout)
print("Writing final Verilog netlist...")
design.evalTclString("write_verilog final.v")

print("OpenROAD physical design flow script finished.")