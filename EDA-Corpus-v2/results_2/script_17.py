# merged_openroad_flow.py

# This script performs a standard OpenROAD digital back-end flow:
# Floorplanning, Placement, CTS, PDN generation, Analysis, and Routing.
# It is based on user requirements and follows best practices for OpenROAD Python scripting.

import odb
import pdn
import openroad as ord
import drt # Detailed router parameters structure
import os # Used for checking VCD file existence

# Get the current design and DB
# Assumes a design is already loaded (e.g., after synthesis and loading libraries)
# using commands like:
# ord.read_liberty("path/to/your/liberty.lib")
# ord.read_lef("path/to/your/lef.lef")
# ord.read_def("path/to/your/synthesized.def") or ord.read_verilog("path/to/your/synthesized.v")
# ord.link_design("TOP_MODULE_NAME") # Replace TOP_MODULE_NAME with your design's top module

design = ord.get_design()
block = design.getBlock()
db = ord.get_db()
tech = db.getTech()

if not block:
    print("Error: No design block found. Please load a design first.")
    exit()

print("--- Design Loaded ---")

# --- Define Parameters ---
# Clock parameters
clock_port_name = "clk"
# Clock name is often derived from the port name; can be explicitly set if needed
clock_period_ns = 20.0

# Floorplan parameters in microns
die_lx_um = 0.0
die_ly_um = 0.0
die_ux_um = 40.0
die_uy_um = 60.0

core_lx_um = 10.0
core_ly_um = 10.0
core_ux_um = 30.0
core_uy_um = 50.0

# Macro placement parameters in microns
macro_fence_lx_um = 15.0
macro_fence_ly_um = 10.0
macro_fence_ux_um = 30.0
macro_fence_uy_um = 40.0
macro_halo_um = 5.0
# Minimum distance between macros in microns (requires recent OpenROAD build)
macro_min_distance_um = 5.0

# Detailed placement parameters in microns
max_disp_x_um = 0.5
max_disp_y_um = 0.5

# CTS parameters
# Replace with a buffer cell name from your technology library
cts_buffer_cell = "BUF_X2" # <<<--- !!! IMPORTANT: Check your library for an appropriate buffer name !!!
# Wire RC values for CTS and routing in ohms/square and Farads/square
wire_resistance_per_sq = 0.03574
wire_capacitance_per_sq = 0.07516

# PDN parameters in microns
# Core Ring M7/M8 around the core area
core_ring_m7_width_um = 2.0
core_ring_m7_spacing_um = 2.0
core_ring_m8_width_um = 2.0
core_ring_m8_spacing_um = 2.0

# Standard Cell Grid - Stripes
# M1 horizontal followpin for standard cell rails
std_cell_grid_m1_width_um = 0.07
# M4 vertical stripes covering standard cells and potentially macro connection points
std_cell_grid_m4_width_um = 1.2
std_cell_grid_m4_spacing_um = 1.2
std_cell_grid_m4_pitch_um = 6.0 # Pitch for vertical M4 straps

# Core Straps on M7/M8 (connecting the rings and covering the core)
core_strap_m7_width_um = 1.4
core_strap_m7_spacing_um = 1.4
core_strap_m7_pitch_um = 10.8 # Pitch for horizontal M7 straps
core_strap_m8_width_um = 1.4
core_strap_m8_spacing_um = 1.4
core_strap_m8_pitch_um = 10.8 # Pitch for vertical M8 straps

# Macro Grid/Ring on M5/M6 (if macros exist), covering macro instances
macro_grid_m5_width_um = 1.2
macro_grid_m5_spacing_um = 1.2
macro_grid_m5_pitch_um = 6.0 # Pitch for horizontal M5 straps
macro_grid_m6_width_um = 1.2
macro_grid_m6_spacing_um = 1.2
macro_grid_m6_pitch_um = 6.0 # Pitch for vertical M6 straps

macro_ring_m5_width_um = 1.5 # Ring width around macros on M5
macro_ring_m5_spacing_um = 1.5 # Ring spacing around macros on M5
macro_ring_m6_width_um = 1.5 # Ring width around macros on M6
macro_ring_m6_spacing_um = 1.5 # Ring spacing around macros on M6

# Via parameters between parallel grids layers (as requested) and other connections
# Pitch of via between two parallel grids is 0 um (unusual, interpreted as place vias wherever possible/needed)
via_cut_pitch_um = 0.0 # <<<--- !!! IMPORTANT: 0 pitch is unusual, verify if this is intended for your technology !!!
# Offset for all cases is 0 um
pdn_offset_um = 0.0

# Routing parameters
# Global router iterations: The prompt mentioned "10 times". In modern GRT, this often refers
# to internal optimization iterations handled by the `globalRoute()` command.
# Detailed routing iterations: Not specified in prompt, setting a reasonable default.
detailed_routing_iterations = 5

# Output file names for intermediate and final steps
def_floorplan = "floorplan.def"
def_macro_placed = "macro_placed.def"
def_global_placed = "global_placed.def"
def_detailed_placed = "detailed_placed.def"
def_cts = "cts.def"
def_filler = "filler.def"
def_pdn = "pdn.def"
def_global_routed = "global_routed.def"
def_detailed_routed = "detailed_routed.def"
def_final = "final.def"
vlog_final = "final.v"
odb_final = "final.odb"

# Placeholder VCD path for analysis
# <<<--- !!! IMPORTANT: Replace with actual VCD file path for accurate analysis !!!
vcd_file_path = "path/to/your/activity.vcd"

print("--- Parameters Defined ---")

# --- Set Clock ---
print(f"Setting clock on port '{clock_port_name}' with period {clock_period_ns} ns...")
clock_port = block.findBTerm(clock_port_name)
if not clock_port:
    print(f"Error: Clock port '{clock_port_name}' not found in the design.")
    # Depending on flow requirements, you might exit here or proceed cautiously
    # exit() # Uncomment to exit if clock port is mandatory
else:
    # Use TCL commands for clock definition as it's a standard approach
    design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}]")
    # Propagate the clock signal throughout the design
    design.evalTclString("set_propagated_clock [all_clocks]")
    print("Clock set.")

# Set wire RC values using TCL commands as requested
print(f"Setting wire RC values: R={wire_resistance_per_sq}, C={wire_capacitance_per_sq}...")
design.evalTclString(f"set_wire_rc -clock -resistance {wire_resistance_per_sq} -capacitance {wire_capacitance_per_sq}")
design.evalTclString(f"set_wire_rc -signal -resistance {wire_resistance_per_sq} -capacitance {wire_capacitance_per_sq}")
print("Wire RC values set.")

# --- Floorplan ---
print("Starting floorplan...")
floorplan = design.getFloorplan()

# Convert micron coordinates to DBU (Database Units)
die_area_dbu = odb.Rect(design.micronToDBU(die_lx_um), design.micronToDBU(die_ly_um),
                        design.micronToDBU(die_ux_um), design.micronToDBU(die_uy_um))
core_area_dbu = odb.Rect(design.micronToDBU(core_lx_um), design.micronToDBU(core_ly_um),
                         design.micronToDBU(core_ux_um), design.micronToDBU(core_uy_um))

# Find a site definition. This is highly technology-dependent.
# Replace "YOUR_SITE_NAME" with the actual site name from your technology LEF/library.
site = floorplan.findSite("YOUR_SITE_NAME") # <<<--- !!! IMPORTANT: Replace with actual site name !!!
if not site:
    # Try some common default site names if the specified one is not found
    default_sites = ["FreePDK45_38x28_10R_NP_162NW_34O", "core", "stdcell"] # Add other potential defaults
    for default_site_name in default_sites:
        site = floorplan.findSite(default_site_name)
        if site:
            print(f"Warning: Site 'YOUR_SITE_NAME' not found. Using default site '{default_site_name}'.")
            break

if not site:
    print("Error: Site not found in library. Please check your technology LEF/library and the specified site name.")
    exit()

# Initialize the floorplan with the defined areas and site
floorplan.initFloorplan(die_area_dbu, core_area_dbu, site)
# Create placement tracks based on the site definition
floorplan.makeTracks()
print("Floorplan complete.")

# Write DEF file after floorplanning
design.writeDef(def_floorplan)
print(f"Saved floorplan DEF: {def_floorplan}")

# --- Macro Placement ---
print("Checking for macros...")
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

if macros:
    print(f"Found {len(macros)} macros. Performing macro placement...")
    mpl = design.getMacroPlacer()

    # Define macro placement fence region in microns
    fence_lx_um = macro_fence_lx_um
    fence_ly_um = macro_fence_ly_um
    fence_ux_um = macro_fence_ux_um
    fence_uy_um = macro_fence_uy_um

    # Define halo around macros in microns
    macro_halo_um = macro_halo_um

    # Define minimum distance between macros in microns (requires recent build)
    macro_min_distance_dbu = design.micronToDBU(macro_min_distance_um)

    # Get layer object for snap layer (assuming metal4 based on examples, technology dependent)
    # Replace "metal4" with the layer appropriate for snapping macro pins in your technology
    snap_layer_name = "metal4" # <<<--- !!! IMPORTANT: Check your technology layer names and purposes !!!
    snap_layer = tech.findLayer(snap_layer_name)
    # Macro placer snap layer parameter expects the routing level (integer)
    snap_layer_level = snap_layer.getRoutingLevel() if snap_layer else 0
    if not snap_layer:
        print(f"Warning: Macro snap layer '{snap_layer_name}' not found. Macro pin snapping might not work as expected.")

    # Run macro placement
    # Parameters are in microns for the Python API `place` method
    mpl.place(
        num_threads = 64, # Number of threads for parallel execution
        max_num_macro = len(macros), # Max number of macros to place
        max_num_inst = 0, # Consider all standard cells for avoidance
        halo_width = macro_halo_um, # Halo width in microns
        halo_height = macro_halo_um, # Halo height in microns
        fence_lx = fence_lx_um, # Fence lower-left x in microns
        fence_ly = fence_ly_um, # Fence lower-left y in microns
        fence_ux = fence_ux_um, # Fence upper-right x in microns
        fence_uy = fence_uy_um, # Fence upper-right y in microns
        area_weight = 0.1,
        outline_weight = 50.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 20.0,
        boundary_weight = 30.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        pin_access_th = 0.0,
        target_util = 0.5, # Example target utilization inside fence (adjust based on design/tech)
        target_dead_space = 0.05,
        min_ar = 0.33, # Example min aspect ratio for macro area
        snap_layer = snap_layer_level, # Layer level to snap macro pins
        bus_planning_flag = False, # Bus planning off
        report_directory = "", # No report directory
        # Uncomment the line below if your OpenROAD build supports min_macro_macro_dist parameter
        # min_macro_macro_dist = macro_min_distance_dbu # Minimum distance between macros in DBU
    )
    print("Macro placement complete.")

    # Write DEF file after macro placement
    design.writeDef(def_macro_placed)
    print(f"Saved macro placement DEF: {def_macro_placed}")

else:
    print("No macros found. Skipping macro placement.")
    # Optional: Write the floorplan DEF again under the macro_placed name if no macros
    # design.writeDef(def_macro_placed)


# --- Global Placement ---
print("Starting global placement...")
gpl = design.getReplace()
# Configure global placement parameters
gpl.setTimingDrivenMode(False) # Disable timing-driven mode by default (requires timing setup)
gpl.setRoutabilityDrivenMode(True) # Enable routability-driven mode
gpl.setUniformTargetDensityMode(True) # Use uniform target density
# Set initial placement iterations (prompt mentioned 10, applying to initial place)
gpl.setInitialPlaceMaxIter(10)
# Set initial density penalty factor
gpl.setInitDensityPenalityFactor(0.05)

# Perform initial placement
# Threads should ideally be set based on available CPU cores
gpl.doInitialPlace(threads = 4) # Example thread count
# Perform Nesterov-accelerated placement
gpl.doNesterovPlace(threads = 4) # Example thread count
gpl.reset() # Reset internal state after placement
print("Global placement complete.")

# Write DEF file after global placement
design.writeDef(def_global_placed)
print(f"Saved global placement DEF: {def_global_placed}")

# --- Detailed Placement ---
print("Starting detailed placement...")
opendp = design.getOpendp()

# Define maximum displacement in microns for detailed placement
# The Python API for detailedPlacement expects displacement in microns in recent versions
max_disp_x_um = max_disp_x_um
max_disp_y_um = max_disp_y_um

# Remove filler cells before detailed placement (usually done before final filler insertion,
# but included here based on typical flow order)
# opendp.removeFillers() # Not strictly necessary before the *first* detailed placement

# Perform detailed placement with specified displacement limits
# detailedPlacement parameters: (max_displacement_x_microns, max_displacement_y_microns, cell_type_pattern, is_macro_flag)
opendp.detailedPlacement(max_disp_x_um, max_disp_y_um, "", False) # Empty string for cell type means all non-macro std cells
print("Detailed placement complete.")

# Write DEF file after detailed placement
design.writeDef(def_detailed_placed)
print(f"Saved detailed placement DEF: {def_detailed_placed}")


# --- Clock Tree Synthesis (CTS) ---
print("Starting CTS...")
cts = design.getTritonCts()
parms = cts.getParms()

# Set available clock buffer and root/sink cells using library master names
# Ensure BUF_X2 is available in your loaded libraries
cts.setBufferList(cts_buffer_cell)
cts.setRootBuffer(cts_buffer_cell)
cts.setSinkBuffer(cts_buffer_cell)

# Note: set_wire_rc was already called earlier for clock/signal nets via TCL.

# Run Clock Tree Synthesis
print("Running TritonCTS...")
cts.runTritonCts()
print("CTS complete.")

# Write DEF file after CTS
design.writeDef(def_cts)
print(f"Saved CTS DEF: {def_cts}")

# --- Insert Filler Cells ---
print("Inserting filler cells...")
# Find filler cell masters in the library
# Assumes filler cells have the CORE_SPACER type. Adjust type or search method if needed for your library.
filler_masters = [master for lib in db.getLibs()
                  for master in lib.getMasters()
                  if master.getType() == "CORE_SPACER"]

# Define filler cell prefix (depends on your library naming convention)
# Replace "FILLCELL_" if your filler cells use a different prefix
filler_cells_prefix = "FILLCELL_" # <<<--- !!! IMPORTANT: Check your library filler cell naming convention !!!

if not filler_masters:
    print("Warning: No filler cells with type CORE_SPACER found in library! Skipping filler placement.")
else:
    # Perform filler cell placement in the core area
    # Assumes the core area is already defined by floorplan.
    opendp.fillerPlacement(filler_masters = filler_masters,
                           prefix = filler_cells_prefix,
                           verbose = False)
    print("Filler cell insertion complete.")

    # Write DEF file after filler insertion
    design.writeDef(def_filler)
    print(f"Saved filler DEF: {def_filler}")


# --- Power Delivery Network (PDN) Configuration and Building ---
print("Configuring and building PDN...")
pdngen = design.getPdnGen()

# Set up global power/ground connections
# Identify POWER and GROUND nets. Assume standard net names like VDD and VSS.
# Create nets if they don't exist (basic check).
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

if VDD_net is None:
    print("Creating VDD net.")
    VDD_net = odb.dbNet_create(block, "VDD")
if VSS_net is None:
    print("Creating VSS net.")
    VSS_net = odb.dbNet_create(block, "VSS")

# Mark nets as special PDN nets
VDD_net.setSpecial()
VSS_net.setSpecial()
VDD_net.setSigType("POWER")
VSS_net.setSigType("GROUND")

# Add global connections for standard cell power/ground pins.
# Pin names are technology-dependent. Adjust pinPattern as needed for your library.
print("Setting global connections for standard cells (VDD, VSS)...")
# It's good practice to remove any existing global connects before adding new ones
block.removeGlobalConnect(region=None, instPattern=".*", pinPattern=".*")
# Add global connects - connect pins matching pattern to the respective nets
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VDD$", net=VDD_net, do_connect=True)
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VDDPE$", net=VDD_net, do_connect=True) # Example common VDD pin
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VDDCE$", net=VDD_net, do_connect=True) # Example common VDD pin
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VSS$", net=VSS_net, do_connect=True)
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VSSE$", net=VSS_net, do_connect=True) # Example common VSS pin
# Apply the configured global connections to the design
block.globalConnect()
print("Global connections applied.")

# Set the core power domain with the primary power and ground nets
pdngen.setCoreDomain(power=VDD_net, ground=VSS_net) # Simplified, assuming no switched/secondary nets

# Define dimension variables in DBUs (Database Units)
core_ring_m7_width_dbu = design.micronToDBU(core_ring_m7_width_um)
core_ring_m7_spacing_dbu = design.micronToDBU(core_ring_m7_spacing_um)
core_ring_m8_width_dbu = design.micronToDBU(core_ring_m8_width_um)
core_ring_m8_spacing_dbu = design.micronToDBU(core_ring_m8_spacing_um)

std_cell_grid_m1_width_dbu = design.micronToDBU(std_cell_grid_m1_width_um)
std_cell_grid_m4_width_dbu = design.micronToDBU(std_cell_grid_m4_width_um)
std_cell_grid_m4_spacing_dbu = design.micronToDBU(std_cell_grid_m4_spacing_um)
std_cell_grid_m4_pitch_dbu = design.micronToDBU(std_cell_grid_m4_pitch_um)

core_strap_m7_width_dbu = design.micronToDBU(core_strap_m7_width_um)
core_strap_m7_spacing_dbu = design.micronToDBU(core_strap_m7_spacing_um)
core_strap_m7_pitch_dbu = design.micronToDBU(core_strap_m7_pitch_um)
core_strap_m8_width_dbu = design.micronToDBU(core_strap_m8_width_um)
core_strap_m8_spacing_dbu = design.micronToDBU(core_strap_m8_spacing_um)
core_strap_m8_pitch_dbu = design.micronToDBU(core_strap_m8_pitch_um)

macro_grid_m5_width_dbu = design.micronToDBU(macro_grid_m5_width_um)
macro_grid_m5_spacing_dbu = design.micronToDBU(macro_grid_m5_spacing_um)
macro_grid_m5_pitch_dbu = design.micronToDBU(macro_grid_m5_pitch_um)
macro_grid_m6_width_dbu = design.micronToDBU(macro_grid_m6_width_um)
macro_grid_m6_spacing_dbu = design.micronToDBU(macro_grid_m6_spacing_um)
macro_grid_m6_pitch_dbu = design.micronToDBU(macro_grid_m6_pitch_um)

macro_ring_m5_width_dbu = design.micronToDBU(macro_ring_m5_width_um)
macro_ring_m5_spacing_dbu = design.micronToDBU(macro_ring_m5_spacing_um)
macro_ring_m6_width_dbu = design.micronToDBU(macro_ring_m6_width_um)
macro_ring_m6_spacing_dbu = design.micronToDBU(macro_ring_m6_spacing_um)

# Via pitch 0 um as requested - interpreted as place vias wherever needed / full overlap
via_cut_pitch_dbu = design.micronToDBU(via_cut_pitch_um)
# Offset 0 um as requested
pdn_offset_dbu = design.micronToDBU(pdn_offset_um)

# Get relevant metal layers by name from the technology database
# Replace names if your technology uses different layer names
m1 = tech.findLayer("metal1") # <<<--- !!! IMPORTANT: Check your technology layer names !!!
m4 = tech.findLayer("metal4") # <<<--- !!! IMPORTANT: Check your technology layer names !!!
m5 = tech.findLayer("metal5") # <<<--- !!! IMPORTANT: Check your technology layer names !!!
m6 = tech.findLayer("metal6") # <<<--- !!! IMPORTANT: Check your technology layer names !!!
m7 = tech.findLayer("metal7") # <<<--- !!! IMPORTANT: Check your technology layer names !!!
m8 = tech.findLayer("metal8") # <<<--- !!! IMPORTANT: Check your technology layer names !!!

# Check if required layers are found
if not all([m1, m4, m5, m6, m7, m8]):
    print("Error: One or more required metal layers for PDN not found in technology LEF. Skipping PDN generation.")
    print(f"Required layers status: metal1={m1 is not None}, metal4={m4 is not None}, metal5={m5 is not None}, metal6={m6 is not None}, metal7={m7 is not None}, metal8={m8 is not None}")
    can_build_pdn = False
else:
    can_build_pdn = True


if can_build_pdn:
    # Create the main core grid structure definition covering the core area
    print("Creating core grid structure (for standard cells and main routing layers)...")
    core_grid = pdngen.makeCoreGrid(
        domain=pdngen.findDomain("Core"), # Associate with the Core domain
        name="top_core_grid" # Name for the core grid definition
    )

    # Add stripes (straps) and rings to the core grid definition
    if core_grid:
        # Horizontal standard cell followpin on M1 (covers standard cell power rails)
        # pitch=0 and followpin=True means place stripes wherever standard cell pins are located
        core_grid.addStrip(layer=m1, width=std_cell_grid_m1_width_dbu, pitch=0, offset=0, direction="horizontal", followpin=True)

        # Vertical straps on M4 (part of the core grid, also connects to macros)
        # Use number_of_straps=0 to auto-calculate based on pitch and core area extent
        core_grid.addStrip(layer=m4, width=std_cell_grid_m4_width_dbu, pitch=std_cell_grid_m4_pitch_dbu, offset=pdn_offset_dbu, direction="vertical", number_of_straps=0)

        # Horizontal straps on M7
        core_grid.addStrip(layer=m7, width=core_strap_m7_width_dbu, pitch=core_strap_m7_pitch_dbu, offset=pdn_offset_dbu, direction="horizontal", number_of_straps=0)

        # Vertical straps on M8
        core_grid.addStrip(layer=m8, width=core_strap_m8_width_dbu, pitch=core_strap_m8_pitch_dbu, offset=pdn_offset_dbu, direction="vertical", number_of_straps=0)

        # Rings around the core area on M7 and M8
        # offset and pad_offset are relative to the core/pad boundary respectively
        core_grid.addRing(layer0=m7, width0=core_ring_m7_width_dbu, spacing0=core_ring_m7_spacing_dbu,
                          layer1=m8, width1=core_ring_m8_width_dbu, spacing1=core_ring_m8_spacing_dbu,
                          offset=[pdn_offset_dbu]*4, pad_offset=[pdn_offset_dbu]*4, nets=[], extend=False)

        # Add via connections between adjacent layers in the core grid
        # Via pitch 0 as requested - interpreted as place vias wherever needed / full overlap
        # addVia(layer0, layer1, cut_pitch_x, cut_pitch_y, ...)
        core_grid.addVia(layer0=m1, layer1=m4, cut_pitch_x=via_cut_pitch_dbu, cut_pitch_y=via_cut_pitch_dbu)
        core_grid.addVia(layer0=m4, layer1=m7, cut_pitch_x=via_cut_pitch_dbu, cut_pitch_y=via_cut_pitch_dbu)
        core_grid.addVia(layer0=m7, layer1=m8, cut_pitch_x=via_cut_pitch_dbu, cut_pitch_y=via_cut_pitch_dbu)

        print("Core grid structure defined.")

    # Create separate PDN structures specifically for macro blocks if they exist, on M5/M6
    if macros:
        print(f"Creating macro instance grid structure for {len(macros)} macros...")

        # Define a grid specifically for instances (macros)
        # This grid applies rules *relative* to the instances it covers, within a specified halo
        macro_instance_grid = pdngen.makeGrid(
            domain=pdngen.findDomain("Core"), # Still belongs to the Core domain
            name="macro_instance_grid",
            type=pdn.INSTANCE, # Specify that this grid applies to instances
            instances=macros, # List of macro instances it applies to
            # Halo around macros where this grid structure should be placed or connected
            # Use macro_halo_um for this halo
            halo=[design.micronToDBU(macro_halo_um)]*4, # Halo in DBU [left, bottom, right, top]
            pg_pins_to_boundary=True # Connect macro PG pins to the grid boundary within the halo
        )

        if macro_instance_grid:
             # Add rings around the boundary of the macro instance grid area (within the halo) on M5 and M6
            macro_instance_grid.addRing(layer0=m5, width0=macro_ring_m5_width_dbu, spacing0=macro_ring_m5_spacing_dbu,
                                        layer1=m6, width1=macro_ring_m6_width_dbu, spacing1=macro_ring_m6_spacing_dbu,
                                        offset=[pdn_offset_dbu]*4, pad_offset=[pdn_offset_dbu]*4, nets=[], extend=False) # Offset from macro instance boundary / halo boundary

            # Add horizontal straps on M5 within the macro instance grid area/halo
            macro_instance_grid.addStrip(layer=m5, width=macro_grid_m5_width_dbu, pitch=macro_grid_m5_pitch_dbu, offset=pdn_offset_dbu, direction="horizontal", number_of_straps=0)

            # Add vertical straps on M6 within the macro instance grid area/halo
            macro_instance_grid.addStrip(layer=m6, width=macro_grid_m6_width_dbu, pitch=macro_grid_m6_pitch_dbu, offset=pdn_offset_dbu, direction="vertical", number_of_straps=0)

            # Add vias connecting layers within the macro grid and connecting macro grid to core grid layers
            # Via pitch 0 as requested
            # Connections within macro grid layers
            macro_instance_grid.addVia(layer0=m5, layer1=m6, cut_pitch_x=via_cut_pitch_dbu, cut_pitch_y=via_cut_pitch_dbu)
            # Connections from macro grid layers to core grid layers (e.g., M4 -> M5, M6 -> M7)
            # These vias are placed within the macro instance grid's halo area
            macro_instance_grid.addVia(layer0=m4, layer1=m5, cut_pitch_x=via_cut_pitch_dbu, cut_pitch_y=via_cut_pitch_dbu)
            macro_instance_grid.addVia(layer0=m6, layer1=m7, cut_pitch_x=via_cut_pitch_dbu, cut_pitch_y=via_cut_pitch_dbu)

            print("Macro instance grid structure defined.")

        elif (not m5 or not m6):
             print("Warning: Macros found, but required metal layers (M5, M6) for macro PDN were not found.")
    elif not macros:
         print("No macros found. Skipping macro PDN configuration.")

    # Verify the PDN setup configuration
    print("Checking PDN setup...")
    pdngen.checkSetup()
    print("PDN setup verified.")

    # Build the configured power grids in the design database
    # The 'False' argument indicates this build is for physical shapes, not power estimation setup
    print("Building power grids...")
    pdngen.buildGrids(False)
    print("Power grids built.")

    # Write the created PDN shapes and connections to the design database
    print("Writing PDN to database...")
    pdngen.writeToDb(True) # True commits the changes to the database
    print("PDN written to database.")

    # Reset temporary shapes used during PDN generation
    pdngen.resetShapes()
    print("PDN configuration and building complete.")

    # Write DEF file after PDN generation
    design.writeDef(def_pdn)
    print(f"Saved PDN DEF: {def_pdn}")

else:
    print("PDN generation skipped due to missing metal layers.")


# --- IR Drop Analysis ---
print("Starting IR drop analysis...")
# Note: Accurate IR drop analysis requires parasitics (SPEF) and switching activity (VCD) files
# to be loaded prior to this step.
# Example commands to load SPEF and VCD (should be run BEFORE this script or added near the start):
# design.evalTclString("read_spef path/to/your/design.spef")
# design.evalTclString(f"read_activity -VCD {vcd_file_path}")

ohmms = design.getOhmms()

# Attempt to load VCD if the file exists and is not the placeholder path
if vcd_file_path != "path/to/your/activity.vcd" and os.path.exists(vcd_file_path):
     try:
         print(f"Attempting to read VCD file: {vcd_file_path}")
         design.evalTclString(f"read_activity -VCD {vcd_file_path}")
         print("VCD file read successfully.")
     except Exception as e:
         print(f"Warning: Failed to read VCD file '{vcd_file_path}'. Power and IR drop analysis may be inaccurate or fail.")
         print(f"Error: {e}")
else:
    print(f"Warning: VCD file '{vcd_file_path}' not found or is a placeholder. Power and IR drop analysis may be inaccurate or fail.")
    print("Please replace 'path/to/your/activity.vcd' with a valid VCD file path and ensure parasitics are loaded.")


# Perform IR drop analysis on M1 layer nodes for VDD and VSS nets as requested
# Analysis requires the Ohmms tool, VDD/VSS nets, and the target layer (M1).
if m1 and VDD_net and VSS_net:
    try:
        print(f"Analyzing IR drop on {m1.getName()} layer...")
        ohmms.analyze(layer=m1, vsrc=VDD_net, gnd=VSS_net)
        print("IR drop analysis complete.")
        # Report the results
        print("--- IR Drop Analysis Report ---")
        ohmms.report_ir_drop()
        print("-----------------------------")
    except Exception as e:
        print(f"Warning: Could not perform IR drop analysis.")
        print(f"Ensure parasitics (SPEF) are loaded, activity (VCD) is loaded, and nets/layers are valid.")
        print(f"Error: {e}")
else:
    print("Warning: IR drop analysis skipped due to missing M1 layer, VDD net, or VSS net.")


# --- Power Analysis ---
print("Starting power analysis...")
# Note: Accurate power analysis requires timing analysis to be run (read_liberty, read_sdc, update_timing)
# and activity (VCD) loaded. The VCD loading is attempted above.
# Ensure timing is updated before reporting power, especially after CTS or SPEF loading.
# Example commands (should be run BEFORE this script or added earlier):
# design.evalTclString("read_sdc path/to/your/constraints.sdc")
# design.evalTclString("update_timing") # Required after design changes like CTS or SPEF loading

opensta = design.getOpenSta()
try:
    # Run timing update if it hasn't been run already in the flow (e.g., after CTS/SPEF)
    # design.evalTclString("update_timing") # Uncomment if timing update is needed here

    print("Reporting power (switching, leakage, internal, total)...")
    opensta.report_power() # Reports dynamic (switching, internal) and static (leakage) power
    print("Power analysis report generated.")
except Exception as e:
     print(f"Warning: Could not perform power analysis.")
     print(f"Ensure timing is setup (read_liberty, read_sdc, update_timing) and activity (VCD) is loaded.")
     print(f"Error: {e}")


# --- Routing ---
print("Starting routing stages...")
grt = design.getGlobalRouter()
drter = design.getTritonRoute()

# Determine routing layer levels based on defined layer objects
# Assuming metal1 is the bottom routing layer and metal7 is the top routing layer for signal/clock
if not m1 or not m7:
    print("Error: Could not find metal1 or metal7 layers for routing. Skipping routing.")
    can_route = False
else:
    signal_low_layer_level = m1.getRoutingLevel()
    signal_high_layer_level = m7.getRoutingLevel()
    clk_low_layer_level = m1.getRoutingLevel() # Clock can use the same or a different range
    clk_high_layer_level = m7.getRoutingLevel()

    can_route = True

    # --- Global Routing ---
    print("Starting global routing...")
    # Set minimum and maximum routing layers for signal nets
    grt.setMinRoutingLayer(signal_low_layer_level)
    grt.setMaxRoutingLayer(signal_high_layer_level)
    # Set minimum and maximum routing layers for clock nets
    grt.setMinLayerForClock(clk_low_layer_level)
    grt.setMaxLayerForClock(clk_high_layer_level)

    # Set adjustment factor (higher value reserves more routing resources, can impact timing)
    grt.setAdjustment(0.5) # Keep value from Gemini draft
    # Enable verbose output
    grt.setVerbose(True)

    # Run global routing. True enables timing-driven routing.
    # The prompt mentioned "10 iterations" for the global router; this is typically handled internally
    # by the globalRoute() command with timing/congestion optimization enabled.
    print("Running global route (timing-driven)...")
    grt.globalRoute(True)
    print("Global routing complete.")

    # Write DEF file after global routing
    design.writeDef(def_global_routed)
    print(f"Saved global routed DEF: {def_global_routed}")


    # --- Detailed Routing ---
    print("Starting detailed routing...")
    # Create a parameter structure for detailed routing
    params = drt.ParamStruct()

    # Configure detailed routing parameters
    params.drouteEndIter = detailed_routing_iterations # Number of detailed routing iterations
    # Set bottom and top routing layers by name (required by TritonRoute API)
    params.bottomRoutingLayer = m1.getName()
    params.topRoutingLayer = m7.getName()
    params.enableViaGen = True # Enable via generation
    params.verbose = 1 # Verbosity level (0: off, 1: normal, 2: high)
    params.cleanPatches = True # Clean up routing patches after detailed routing
    params.doPa = True # Enable post-route repair (fixes violations)
    # Other parameters from Gemini draft and common settings
    params.outputMazeFile = "" # No debug maze file
    params.outputDrcFile = "" # No DRC output file from detailed router (use official DRC tool later)
    params.outputCmapFile = ""
    params.outputGuideCoverageFile = ""
    # params.dbProcessNode = "" # Technology process node (optional, consult technology documentation)
    # params.viaInPinBottomLayer = "" # Optional: bottom layer for via-in-pin
    # params.viaInPinTopLayer = "" # Optional: top layer for via-in-pin
    params.orSeed = -1 # Random seed for optimization (-1 means time-based)
    params.orK = 0 # Optimization parameter (keep default 0)
    # params.singleStepDR = False # Do not run single-step detailed routing (normal mode)
    params.minAccessPoints = 1 # Minimum access points for pins
    params.saveGuideUpdates = False # Do not save guide updates (saves disk space)

    # Set the configured parameters for the detailed router
    drter.setParams(params)

    # Run detailed routing
    print("Running TritonRoute...")
    drter.main()
    print("Detailed routing complete.")

    # Write DEF file after detailed routing
    design.writeDef(def_detailed_routed)
    print(f"Saved detailed routed DEF: {def_detailed_routed}")

else:
    print("Routing skipped due to missing required metal layers.")


# --- Save Final Outputs ---
print("Saving final output files...")
# Write final DEF file containing the complete physical design
design.writeDef(def_final)
print(f"Saved final DEF: {def_final}")

# Write final Verilog netlist (includes placed cells, updated netlist from synthesis/CTS)
# Use TCL command as write_verilog is a TCL command
design.evalTclString(f"write_verilog {vlog_final}")
print(f"Saved final Verilog: {vlog_final}")

# Write final ODB database file for archiving or further processing
design.writeDb(odb_final)
print(f"Saved final ODB: {odb_final}")

print("--- OpenROAD Flow Script Complete ---")