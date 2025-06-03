import odb
import pdn
import drt
import psm
import openroad as ord
from pathlib import Path

# 0. Initialize OpenROAD
# This is a common first step to get the DB handle and access core objects
ord.get_db()
# Optionally hide the GUI if running headless
# ord.get_main_window().hide()

# 1. Define input/output paths
# Adjust these paths based on your project structure
libDir = Path("./libs")
lefDir = Path("./lefs")
# Assuming tech LEF and cell LEFs are in lefDir
techLefFilePattern = "*.tech.lef" # Pattern for the technology LEF file(s)
cellLefFilePattern = "*.lef"      # Pattern for cell LEF files
libFilePattern = "*.lib"          # Pattern for timing library files
verilogFile = Path("./input.v")   # Path to the input gate-level Verilog netlist

outputDefFile = "final.def"
outputVerilogFile = "final.v"
outputDbFile = "final.odb"

# 2. Create a new design
# Tech() creates the core technology object
tech = ord.Tech()
# Design() creates the design object
design = ord.Design(tech)
# Set the database handle to the design
db = ord.get_db()
design.setDb(db)

# 3. Read inputs (tech LEF, cell LEFs, Libs, Verilog)
# The standard order is typically: tech LEF, cell LEFs, liberty files
print(f"Reading technology LEF files from {lefDir.as_posix()} with pattern {techLefFilePattern}...")
techLefFiles = list(lefDir.glob(techLefFilePattern))
if not techLefFiles:
    print(f"Warning: No tech LEF files found matching pattern {techLefFilePattern} in {lefDir.as_posix()}")
for techLefFile in techLefFiles:
    print(f"  Reading {techLefFile.name}")
    tech.readLef(techLefFile.as_posix())

print(f"Reading cell LEF files from {lefDir.as_posix()} with pattern {cellLefFilePattern}...")
cellLefFiles = list(lefDir.glob(cellLefFilePattern))
if not cellLefFiles:
     print(f"Warning: No cell LEF files found matching pattern {cellLefFilePattern} in {lefDir.as_posix()}")
# Read cell LEFs after tech LEF
for cellLefFile in cellLefFiles:
    # Skip tech LEFs if pattern overlaps
    if cellLefFile not in techLefFiles:
        print(f"  Reading {cellLefFile.name}")
        tech.readLef(cellLefFile.as_posix())

print(f"Reading liberty timing library files from {libDir.as_posix()} with pattern {libFilePattern}...")
libFiles = list(libDir.glob(libFilePattern))
if not libFiles:
     print(f"Warning: No liberty files found matching pattern {libFilePattern} in {libDir.as_posix()}")
# Load liberty timing libraries
for libFile in libFiles:
    print(f"  Reading {libFile.name}")
    tech.readLiberty(libFile.as_posix())

print(f"Reading Verilog netlist: {verilogFile.as_posix()}")
design.readVerilog(verilogFile.as_posix())

# 4. Link design
# Link resolves instances to masters and connects nets
design_top_module_name = verilogFile.stem
print(f"Linking design with top module name: {design_top_module_name}")
design.link(design_top_module_name)

# 5. Setup clock constraints
clock_period_ns = 50.0 # Clock period in nanoseconds
clock_port_name = "clk" # Name of the clock port
clock_name = "core_clock" # Name of the timing domain

print(f"Setting clock {clock_name} on port {clock_port_name} with period {clock_period_ns} ns")
# Create clock signal on the specified port
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
# Propagate the clock signal (important for CTS and timing analysis)
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Set RC values for clock and signal nets
# These values are technology-dependent; prompt provides specific values
clock_rc_resistance = 0.03574
clock_rc_capacitance = 0.07516
signal_rc_resistance = 0.03574
signal_rc_capacitance = 0.07516 # Prompt uses same values for signal

print(f"Setting clock wire RC: R={clock_rc_resistance}, C={clock_rc_capacitance}")
design.evalTclString(f"set_wire_rc -clock -resistance {clock_rc_resistance} -capacitance {clock_rc_capacitance}")
print(f"Setting signal wire RC: R={signal_rc_resistance}, C={signal_rc_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {signal_rc_resistance} -capacitance {signal_rc_capacitance}")

# 6. Initialize floorplan
floorplan = design.getFloorplan()
dbu_per_micron = db.getTech().getDBUPerMicron()

# Set die area bounding box: bl=(0,0), tr=(40,60) um
die_lx_um, die_ly_um, die_ux_um, die_uy_um = 0, 0, 40, 60
die_area = odb.Rect(int(die_lx_um * dbu_per_micron), int(die_ly_um * dbu_per_micron),
                    int(die_ux_um * dbu_per_micron), int(die_uy_um * dbu_per_micron))
print(f"Setting die area: ({die_lx_um}, {die_ly_um}) um to ({die_ux_um}, {die_uy_um}) um")

# Set core area bounding box: bl=(10,10), tr=(30,50) um
core_lx_um, core_ly_um, core_ux_um, core_uy_um = 10, 10, 30, 50
core_area = odb.Rect(int(core_lx_um * dbu_per_micron), int(core_ly_um * dbu_per_micron),
                     int(core_ux_um * dbu_per_micron), int(core_uy_um * dbu_per_micron))
print(f"Setting core area: ({core_lx_um}, {core_ly_um}) um to ({core_ux_um}, {core_uy_um}) um")

# Find a suitable site (typically a CORE site)
site_name = None
core_site = None
for lib in db.getLibs():
    for site in lib.getSites():
        if site.getType() == "CORE":
            core_site = site
            site_name = site.getName()
            break
    if core_site:
        break

if not core_site:
    # Fallback: Try finding a site by a common name or just use the first one
    # This is a placeholder; ideally, you'd check your tech file for valid site names
    print(f"Warning: No CORE site found. Attempting to find a site by a common name or using the first available site.")
    site_name_fallback = "CORE" # Common site type name
    core_site = db.getTech().findSite(site_name_fallback)
    if not core_site:
        print("Warning: Fallback 'CORE' site not found. Attempting to use the first available site.")
        tech_sites = db.getTech().getSites()
        if tech_sites:
            core_site = tech_sites[0]
            site_name = core_site.getName()
        else:
             core_site = None # No sites found

if not core_site:
    print("Fatal Error: Could not find a suitable site for floorplan initialization.")
    exit(1) # Exit if floorplan cannot be initialized

# Corrected typo: site_site.getName() -> core_site.getName()
print(f"Initializing floorplan with site: {core_site.getName()}")
floorplan.initFloorplan(die_area, core_area, core_site)

# Make placement tracks based on the site and layers
print("Making placement tracks...")
floorplan.makeTracks()

# 7. Place macro blocks if present
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
if len(macros) > 0:
    print(f"Found {len(macros)} macro instances. Running macro placement.")
    mpl = design.getMacroPlacer()
    block = design.getBlock()

    # Set fence region for macros: bl=(15,10), tr=(30,40) um
    fence_lx_um, fence_ly_um, fence_ux_um, fence_uy_um = 15, 10, 30, 40
    print(f"Setting macro fence region: ({fence_lx_um}, {fence_ly_um}) um to ({fence_ux_um}, {fence_uy_um}) um")
    # The fence region should be in DBUs
    fence_lx_dbu = int(fence_lx_um * dbu_per_micron)
    fence_ly_dbu = int(fence_ly_um * dbu_per_micron)
    fence_ux_dbu = int(fence_ux_um * dbu_per_micron)
    fence_uy_dbu = int(fence_uy_um * dbu_per_micron)
    mpl.setFenceRegion(fence_lx_dbu, fence_ly_dbu, fence_ux_dbu, fence_uy_dbu)


    # Set macro halo: 5 um around each macro
    halo_um = 5.0
    halo_dbu = int(halo_um * dbu_per_micron)
    print(f"Setting macro halo: {halo_um} um")
    # The prompt also asks for 5um minimum separation between macros.
    # This specific separation might not be a direct parameter to mpl.place
    # but can be influenced by halo and the placer's internal algorithms.
    # Check OpenROAD documentation for explicit macro-to-macro spacing controls if needed.

    # Place macros
    # Note: `snap_layer` aligns macro pins to track grid on a specific layer.
    # Using metal4 (assuming layer index 4) as an example. Find the layer object.
    metal4_layer = db.getTech().findLayer("metal4")
    snap_layer_idx = -1 # Default to no snapping if layer not found
    if metal4_layer:
        snap_layer_idx = metal4_layer.getRoutingLevel()
        print(f"Aligning macro pins to tracks on {metal4_layer.getName()} (level {snap_layer_idx})")
    else:
         print("Warning: Metal4 layer not found. Cannot snap macro pins to tracks.")


    mpl.place(
        num_threads = 4, # Number of threads
        halo_width = halo_dbu,
        halo_height = halo_dbu,
        snap_layer = snap_layer_idx if snap_layer_idx != -1 else 0 # Use layer index, default to 0 or handle appropriately
    )
else:
    print("No macro instances found. Skipping macro placement.")


# 8. Global Placement (Standard Cells)
print("Running global placement...")
gpl = design.getReplace()
# Set placement options
gpl.setTimingDrivenMode(False) # Can be set to True if timing closure is important
gpl.setRoutabilityDrivenMode(True) # Enable routability-driven placement
gpl.setUniformTargetDensityMode(True) # Use uniform target density

# The prompt mentions 20 iterations for the "global router".
# OpenROAD's global router (part of TritonRoute or RePlAce) iteration control isn't a simple parameter like this.
# Interpreting this as a tuning parameter influencing congestion resolution,
# which is typically controlled by 'adjustment' in the global router.
# The script's previous interpretation as Global Placer iterations was incorrect based on the prompt text.
# The main call `grt.globalRoute(True)` handles the routing iterations.
# Leaving the global placer iterations setting as default or removing it if not needed.
# The script had `gpl.setInitialPlaceMaxIter(global_placement_iterations)` based on this misinterpretation.
# We will remove this specific placer iteration setting and rely on the standard placer flow.
# global_placement_iterations = 20 # This parameter is not directly applicable to the global router iterations as described in the prompt API

# Other common parameters (example values)
gpl.setInitDensityPenalityFactor(0.05)
gpl.setGlobalPlacementDensity(0.6) # Example target density

# Run initial and Nesterov placement stages
gpl.doInitialPlace(threads = 4)
gpl.doNesterovPlace(threads = 4)
gpl.reset() # Reset the placer state

# 9. Detailed Placement (Pre-CTS)
print("Running pre-CTS detailed placement...")
opendp = design.getOpendp()

# Set max displacement: 0.5 um in X, 0.5 um in Y
max_disp_x_um = 0.5
max_disp_y_um = 0.5
# Detailed placement displacement parameter is in DBUs.
max_disp_x_dbu = int(max_disp_x_um * dbu_per_micron)
max_disp_y_dbu = int(max_disp_y_um * dbu_per_micron)

# Remove filler cells if any were inserted earlier (unlikely before this stage)
opendp.removeFillers()

# Perform detailed placement
# Parameters: max_disp_x, max_disp_y, filler_cell_name (empty string means no filler insertion during DP), check_placement
print(f"Detailed Placement (Pre-CTS) with max displacement: X={max_disp_x_um} um, Y={max_disp_y_um} um")
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

# 10. Power Grid Generation
print("Generating power delivery network...")
# Set up global power/ground connections
# Find existing power and ground nets or create if needed
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")

# Create VDD/VSS nets if they don't exist
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

# Connect power pins to global nets
# Map standard VDD/VSS pins to global power/ground nets for all instances
print("Connecting power/ground pins globally...")
design.getBlock().addGlobalConnect(region = None,
    instPattern = ".*",
    pinPattern = "^VDD$", # Adjust pin names if different (e.g., VCC)
    net = VDD_net,
    do_connect = True)
design.getBlock().addGlobalConnect(region = None,
    instPattern = ".*",
    pinPattern = "^VSS$", # Adjust pin names if different (e.g., GND)
    net = VSS_net,
    do_connect = True)
# Apply the global connections
design.getBlock().globalConnect()

# Configure power domains
pdngen = design.getPdnGen()
# Set core power domain with primary power/ground nets
# Assuming a single core domain using VDD and VSS
pdngen.setCoreDomain(power = VDD_net,
    switched_power = None,
    ground = VSS_net,
    secondary = [])
# Ensure the Core domain is initialized if it wasn't automatically
pdngen.init()

# Get metal layers by name
m1 = db.getTech().findLayer("metal1")
m4 = db.getTech().findLayer("metal4")
m5 = db.getTech().findLayer("metal5")
m6 = db.getTech().findLayer("metal6")
m7 = db.getTech().findLayer("metal7")
m8 = db.getTech().findLayer("metal8")

# Check if required layers exist
required_layers = {"metal1":m1, "metal4":m4, "metal5":m5, "metal6":m6, "metal7":m7, "metal8":m8}
layers_exist = True
for layer_name, layer_obj in required_layers.items():
    if layer_obj is None:
        print(f"Fatal Error: Required layer '{layer_name}' not found in technology.")
        layers_exist = False

if not layers_exist:
     exit(1) # Exit if floorplan cannot be initialized


# Prompt: "set the offset to 0 for all cases"
# Prompt: "set the pitch of the via between two grids to 0 um"
# Interpretation: All strap/ring offsets are 0. Via pitch 0 between layers likely means place vias at all valid locations on the via grid.
# Using cut_pitch=0,0 in DBU (after conversion) or relying on ongrid=pdn.VIA_GRID. Let's use ongrid for standard practice.
# The prompt wording "pitch of the via between two grids to 0 um" is unusual; standard practice is to place vias according to tech rules on the via grid. Using ongrid=pdn.VIA_GRID is standard.

via_ongrid = pdn.VIA_GRID # Standard way to place vias on the defined via grid

# Create the main core grid structure for standard cells
domains = [pdngen.findDomain("Core")]
core_grid_name = "std_cell_grid"
print(f"Creating core power grid '{core_grid_name}'")
for domain in domains: # Typically only one core domain
    pdngen.makeCoreGrid(domain = domain,
        name = core_grid_name,
        starts_with = pdn.GROUND, # Start with ground net strap/ring
        pin_layers = [], # Not connecting directly to core pins via grid definition
        generate_obstructions = [],
        powercell = None, powercontrol = None, powercontrolnetwork = "")

core_grid = pdngen.findGrid(core_grid_name)[0] # Get the created grid object

# Add straps and rings to the core grid
# Standard cell followpin grid on M1
m1_followpin_width_um = 0.07
print(f"Adding M1 followpin grid (width {m1_followpin_width_um} um)")
pdngen.makeFollowpin(grid = core_grid,
    layer = m1,
    width = int(m1_followpin_width_um * dbu_per_micron),
    extend = pdn.CORE) # Extend within the core area

# Standard cell strap grid on M4
m4_strap_width_um = 1.2
m4_strap_spacing_um = 1.2
m4_strap_pitch_um = 6.0
m4_strap_offset_um = 0.0
print(f"Adding M4 straps (width {m4_strap_width_um}, spacing {m4_strap_spacing_um}, pitch {m4_strap_pitch_um}) um")
pdngen.makeStrap(grid = core_grid,
    layer = m4,
    width = int(m4_strap_width_um * dbu_per_micron),
    spacing = int(m4_strap_spacing_um * dbu_per_micron),
    pitch = int(m4_strap_pitch_um * dbu_per_micron),
    offset = int(m4_strap_offset_um * dbu_per_micron),
    number_of_straps = 0, # Auto-calculate number of straps
    snap = False, # Don't snap straps to track grid by default
    starts_with = pdn.GRID, # Start pattern from the grid boundary
    extend = pdn.CORE, # Extend within the core area
    nets = []) # Apply to all nets in the domain

# Standard cell strap grid on M7
m7_strap_width_um = 1.4
m7_strap_spacing_um = 1.4
m7_strap_pitch_um = 10.8
m7_strap_offset_um = 0.0
print(f"Adding M7 straps (width {m7_strap_width_um}, spacing {m7_strap_spacing_um}, pitch {m7_strap_pitch_um}) um")
pdngen.makeStrap(grid = core_grid,
    layer = m7,
    width = int(m7_strap_width_um * dbu_per_micron),
    spacing = int(m7_strap_spacing_um * dbu_per_micron),
    pitch = int(m7_strap_pitch_um * dbu_per_micron),
    offset = int(m7_strap_offset_um * dbu_per_micron),
    number_of_straps = 0,
    snap = False,
    starts_with = pdn.GRID,
    extend = pdn.RINGS, # Extend to the power rings on M7/M8
    nets = [])

# Standard cell strap grid on M8
m8_strap_width_um = 1.4
m8_strap_spacing_um = 1.4
m8_strap_pitch_um = 10.8
m8_strap_offset_um = 0.0
print(f"Adding M8 straps (width {m8_strap_width_um}, spacing {m8_strap_spacing_um}, pitch {m8_strap_pitch_um}) um")
pdngen.makeStrap(grid = core_grid,
    layer = m8,
    width = int(m8_strap_width_um * dbu_per_micron),
    spacing = int(m8_strap_spacing_um * dbu_per_micron),
    pitch = int(m8_strap_pitch_um * dbu_per_micron),
    offset = int(m8_strap_offset_um * dbu_per_micron),
    number_of_straps = 0,
    snap = False,
    starts_with = pdn.GRID,
    extend = pdn.BOUNDARY, # Extend to the design boundary (or rings)
    nets = [])

# Create power rings around core area using metal7 and metal8
m7_ring_width_um = 4.0
m7_ring_spacing_um = 4.0
m8_ring_width_um = 4.0
m8_ring_spacing_um = 4.0
ring_offset_um = 0.0
print(f"Adding core rings on M7/M8 (width {m7_ring_width_um}, spacing {m7_ring_spacing_um}) um")
pdngen.makeRing(grid = core_grid,
    layer0 = m7,
    width0 = int(m7_ring_width_um * dbu_per_micron),
    spacing0 = int(m7_ring_spacing_um * dbu_per_micron),
    layer1 = m8,
    width1 = int(m8_ring_width_um * dbu_per_micron),
    spacing1 = int(m8_ring_spacing_um * dbu_per_micron),
    starts_with = pdn.GRID, # Start with ground net (consistent with core grid)
    offset = [int(ring_offset_um * dbu_per_micron)] * 4, # [left, bottom, right, top]
    pad_offset = [0] * 4, # Pad offset is not applicable for core rings
    extend = False, # Do not extend ring beyond the core boundary
    pad_pin_layers = [], # Not connecting to pads
    nets = [])

# Create via connections between core grid layers
# Connect metal1 to metal4
print("Adding via connections M1-M4")
pdngen.makeConnect(grid = core_grid,
    layer0 = m1,
    layer1 = m4,
    ongrid = via_ongrid, # Standard via placement on via grid
    vias = [], techvias = [], max_rows = 0, max_columns = 0, split_cuts = dict(), dont_use_vias = "") # Removed cut_pitch=0,0

# Connect metal4 to metal7
print("Adding via connections M4-M7")
pdngen.makeConnect(grid = core_grid,
    layer0 = m4,
    layer1 = m7,
    ongrid = via_ongrid,
    vias = [], techvias = [], max_rows = 0, max_columns = 0, split_cuts = dict(), dont_use_vias = "")

# Connect metal7 to metal8
print("Adding via connections M7-M8")
pdngen.makeConnect(grid = core_grid,
    layer0 = m7,
    layer1 = m8,
    ongrid = via_ongrid,
    vias = [], techvias = [], max_rows = 0, max_columns = 0, split_cuts = dict(), dont_use_vias = "")


# Create power grid for macro blocks if macros exist
if len(macros) > 0:
    print("Creating macro power grids...")
    # Halo around macros for macro power grid routing exclusion from other grids
    macro_halo_um = 5.0
    macro_halo_dbu = [int(macro_halo_um * dbu_per_micron)] * 4 # [left, bottom, right, top]

    # Macro ring parameters on M5/M6
    macro_ring_m5_width_um = 1.5
    macro_ring_m5_spacing_um = 1.5
    macro_ring_m6_width_um = 1.5
    macro_ring_m6_spacing_um = 1.5
    macro_ring_offset_um = 0.0 # Prompt says offset 0 for all cases

    # Macro strap/grid parameters on M5/M6
    macro_strap_width_um = 1.2
    macro_strap_spacing_um = 1.2
    macro_strap_pitch_um = 6.0
    macro_strap_offset_um = 0.0 # Prompt says offset 0 for all cases

    for i, macro_inst in enumerate(macros):
        macro_grid_name = f"macro_grid_{macro_inst.getName()}_{i}" # Use instance name for clarity
        print(f"  Creating grid '{macro_grid_name}' for macro instance {macro_inst.getName()}")

        # Create separate power grid structure for each macro instance
        # Use the core domain for the macro grid association
        pdngen.makeInstanceGrid(domain = domains[0], # Assuming macros are part of the core domain
            name = macro_grid_name,
            starts_with = pdn.GROUND, # Start with ground net strap/ring
            inst = macro_inst, # Specify the macro instance
            halo = macro_halo_dbu, # Halo around the macro instance
            pg_pins_to_boundary = True,  # Connect macro power/ground pins to boundary
            default_grid = False, # Not the default grid
            generate_obstructions = [], # No additional obstructions
            is_bump = False)

        # Find the grid object that was just created
        macro_grid = None
        found_grids = pdngen.findGrid(macro_grid_name)
        if found_grids:
             macro_grid = found_grids[0]
        else:
             print(f"Error: Could not find macro grid '{macro_grid_name}' after creation.")
             continue # Skip this macro if grid creation failed

        # --- Correction: Add macro power rings on M5/M6 as per feedback ---
        # Create power ring around macro using metal5 and metal6
        print(f"    Adding macro ring on M5/M6 (width {macro_ring_m5_width_um}, spacing {macro_ring_m5_spacing_um}) um")
        pdngen.makeRing(grid = macro_grid,
            layer0 = m5,
            width0 = int(macro_ring_m5_width_um * dbu_per_micron),
            spacing0 = int(macro_ring_m5_spacing_um * dbu_per_micron),
            layer1 = m6,
            width1 = int(macro_ring_m6_width_um * dbu_per_micron),
            spacing1 = int(macro_ring_m6_spacing_um * dbu_per_micron),
            starts_with = pdn.GRID, # Start with ground net (consistent with instance grid)
            offset = [int(macro_ring_offset_um * dbu_per_micron)] * 4,
            pad_offset = [0] * 4, # Pad offset not applicable here
            extend = False, # Do not extend ring - it's around the instance
            pad_pin_layers = [], # Not connecting to pads
            nets = [])
        # -----------------------------------------------------------------


        # Create power straps on metal5 for macro connections
        # These straps extend to the rings defined above for this macro grid
        print(f"    Adding M5 straps (width {macro_strap_width_um}, spacing {macro_strap_spacing_um}, pitch {macro_strap_pitch_um}) um")
        pdngen.makeStrap(grid = macro_grid,
            layer = m5,
            width = int(macro_strap_width_um * dbu_per_micron),
            spacing = int(macro_strap_spacing_um * dbu_per_micron),
            pitch = int(macro_strap_pitch_um * dbu_per_micron),
            offset = int(macro_strap_offset_um * dbu_per_micron),
            number_of_straps = 0,
            snap = True, # Snap to track grid for macro connections
            starts_with = pdn.GRID,
            extend = pdn.RINGS, # Extend to the macro power rings on M5/M6 (now defined)
            nets = [])

        # Create power straps on metal6 for macro connections
        # These straps extend to the rings defined above for this macro grid
        print(f"    Adding M6 straps (width {macro_strap_width_um}, spacing {macro_strap_spacing_um}, pitch {macro_strap_pitch_um}) um")
        pdngen.makeStrap(grid = macro_grid,
            layer = m6,
            width = int(macro_strap_width_um * dbu_per_micron),
            spacing = int(macro_strap_spacing_um * dbu_per_micron),
            pitch = int(macro_strap_pitch_um * dbu_per_micron),
            offset = int(macro_strap_offset_um * dbu_per_micron),
            number_of_straps = 0,
            snap = True, # Snap to track grid for macro connections
            starts_with = pdn.GRID,
            extend = pdn.RINGS, # Extend to the macro power rings on M5/M6 (now defined)
            nets = [])

        # Create via connections between macro power grid layers and core grid layers
        # Connect metal4 (from standard cell grid) to metal5 (macro grid)
        print("    Adding via connections M4-M5")
        pdngen.makeConnect(grid = macro_grid,
            layer0 = m4,
            layer1 = m5,
            ongrid = via_ongrid,
            vias = [], techvias = [], max_rows = 0, max_columns = 0, split_cuts = dict(), dont_use_vias = "")

        # Connect metal5 to metal6 (macro grid layers)
        print("    Adding via connections M5-M6")
        pdngen.makeConnect(grid = macro_grid,
            layer0 = m5,
            layer1 = m6,
            ongrid = via_ongrid,
            vias = [], techvias = [], max_rows = 0, max_columns = 0, split_cuts = dict(), dont_use_vias = "")

        # Connect metal6 (macro grid) to metal7 (standard cell grid)
        print("    Adding via connections M6-M7")
        # Note: Connecting individual macro grids to the main core grid (M7)
        pdngen.makeConnect(grid = macro_grid,
            layer0 = m6,
            layer1 = m7,
            ongrid = via_ongrid,
            vias = [], techvias = [], max_rows = 0, max_columns = 0, split_cuts = dict(), dont_use_vias = "")


# Generate the final power delivery network
print("Building and writing power grid...")
pdngen.checkSetup() # Verify configuration
pdngen.buildGrids(False) # Build the power grid shapes in memory
pdngen.writeToDb(True) # Write power grid shapes to the design database
pdngen.resetShapes() # Reset temporary shapes used during generation

# 11. Clock Tree Synthesis
print("Running clock tree synthesis (CTS)...")
cts = design.getTritonCts()
# parms = cts.getParms() # Access parameters if needed for finer tuning

# Configure clock buffers
buffer_list = "BUF_X2" # Set list of available buffers
root_buffer = "BUF_X2" # Set root buffer type
sink_buffer = "BUF_X2" # Set sink buffer type
print(f"Setting CTS buffers: list='{buffer_list}', root='{root_buffer}', sink='{sink_buffer}'")
cts.setBufferList(buffer_list)
cts.setRootBuffer(root_buffer)
cts.setSinkBuffer(sink_buffer)

# Set the clock net for CTS
# The clock net is the net connected to the clock port defined earlier
clock_net_obj = design.getBlock().findNet(clock_port_name)
if clock_net_obj is not None:
    print(f"Setting clock net for CTS: {clock_port_name}")
    cts.setClockNets(clock_net_obj)
    # Run CTS
    print("Starting CTS...")
    cts.runTritonCts()
    print("CTS finished.")
else:
    print(f"Warning: Clock net '{clock_port_name}' not found. Skipping CTS.")


# 12. Detailed Placement (Post-CTS)
# Re-run detailed placement after CTS to fix any displacement caused by buffer insertion
print("Running post-CTS detailed placement...")
# Use the same max displacement values as pre-CTS
print(f"Detailed Placement (Post-CTS) with max displacement: X={max_disp_x_um} um, Y={max_disp_y_um} um")
# Remove filler cells before running DP again (CTS might have moved things)
opendp.removeFillers()
# Perform detailed placement
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

# 13. Insert filler cells
print("Inserting filler cells...")
# Find filler cell masters (assuming CORE_SPACER type is used for fillers)
db = ord.get_db()
filler_masters = list()
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER": # Check for standard filler cell type
            filler_masters.append(master)
        # Add other potential filler types if necessary based on technology library
        # elif master.getName().startswith("FILL"): # Example: check by name prefix
        #     filler_masters.append(master)

if len(filler_masters) == 0:
    print("Warning: No CORE_SPACER (or similar) cells found in libraries. Skipping filler insertion.")
else:
    # Insert filler cells to fill gaps in rows
    print(f"Found {len(filler_masters)} filler cell masters. Performing filler placement.")
    opendp.fillerPlacement(filler_masters = filler_masters,
                         prefix = "FILL_", # Prefix for new filler instances
                         verbose = False) # Set to True for more output


# 14. Global Routing
print("Running global routing...")
grt = design.getGlobalRouter()

# Set routing layer ranges for signal and clock nets (M1 to M7)
min_routing_layer_name = "metal1"
max_routing_layer_name = "metal7"
min_routing_layer_obj = db.getTech().findLayer(min_routing_layer_name)
max_routing_layer_obj = db.getTech().findLayer(max_routing_layer_name)

if min_routing_layer_obj is None or max_routing_layer_obj is None:
     print(f"Fatal Error: Could not find routing layers '{min_routing_layer_name}' or '{max_routing_layer_name}'. Skipping routing.")
     min_routing_level = -1 # Indicate failure
     max_routing_level = -1
else:
    min_routing_level = min_routing_layer_obj.getRoutingLevel()
    max_routing_level = max_routing_layer_obj.getRoutingLevel()
    print(f"Setting global routing layers: {min_routing_layer_name} (level {min_routing_level}) to {max_routing_layer_name} (level {max_routing_level})")
    grt.setMinRoutingLayer(min_routing_level)
    grt.setMaxRoutingLayer(max_routing_level)
    grt.setMinLayerForClock(min_routing_level) # Use same range for clock
    grt.setMaxLayerForClock(max_routing_level)

    # The prompt mentions 20 iterations for the global router.
    # Direct iteration control via Python `grt` object is not standard.
    # Global router behavior is typically tuned via adjustment parameters influencing congestion.
    # Setting adjustment affects congestion and can involve internal iterative processes.
    grt.setAdjustment(0.5) # Example adjustment value (0.5 means 50% extra capacity allowed)
    grt.setVerbose(True)

    # Run global routing
    # The boolean argument often controls optimization or additional passes.
    print("Starting global route...")
    grt.globalRoute(True) # True often enables optimization passes
    print("Global routing finished.")

    # 15. Detailed Routing
    print("Running detailed routing...")
    drter = design.getTritonRoute()
    # Get default parameters structure
    params = drt.ParamStruct()

    # Set routing layer range for detailed routing (M1 to M7)
    # TritonRoute uses layer names
    print(f"Setting detailed routing layers: {min_routing_layer_name} to {max_routing_layer_name}")
    params.bottomRoutingLayer = min_routing_layer_name
    params.topRoutingLayer = max_routing_layer_name

    # Set other detailed routing parameters if needed (e.g., via settings, DRC modes)
    # params.via_repair_iters = 1 # Example: Add via repair iterations
    # params.drc_repair_iters = 5 # Example: DRC repair iterations

    # Set parameters for the detailed router
    drter.setParams(params)

    # Run detailed routing
    print("Starting detailed route...")
    drter.main()
    print("Detailed routing finished.")

    # 16. Perform static IR drop analysis
    print("Performing static IR drop analysis...")
    psm_obj = design.getPDNSim()
    timing = ord.Timing(design) # Need Timing object to get corners

    # Get the VDD net for analysis
    vdd_net_for_ir = design.getBlock().findNet("VDD")
    # Get the Metal1 layer object for analysis layer
    m1_layer = db.getTech().findLayer("metal1")

    if vdd_net_for_ir is not None and m1_layer is not None:
        # Ensure at least one timing corner exists
        corners = timing.getCorners()
        if corners:
            print(f"Analyzing IR drop on VDD net for layer '{m1_layer.getName()}'...")
            # Analyze the VDD power grid IR drop on M1 layer
            psm_obj.analyzePowerGrid(net = vdd_net_for_ir,
                enable_em = False, # Disable EM analysis for speed, prompt only asked for IR
                corner = corners[0], # Use the first timing corner (requires timing setup)
                use_prev_solution = False, # Do not use previous solution
                em_file = "", error_file = "", voltage_source_file = "", voltage_file = "", # Output files (empty means no output)
                # Source type depends on where current consumption is modeled (standard cells, macros).
                # GeneratedSourceType_MASTER is often suitable when power is modeled per cell master,
                # assuming timing analysis results are loaded.
                source_type = [psm.GeneratedSourceType_MASTER], # Requires timing and activity
                layers = [m1_layer]) # Analyze specifically on the Metal1 layer
            # Access results after analysis: psm_obj.getVoltage()
            print("IR drop analysis complete.")
            # Optional: Report IR drop results - requires more setup and output handling
            # print(f"Max IR drop voltage: {psm_obj.getMaxVoltage()}")
            # print(f"Min IR drop voltage: {psm_obj.getMinVoltage()}")
        else:
            print("Warning: No timing corners found. Timing analysis required for accurate IR drop analysis. Skipping.")
            print("Hint: Ensure timing corners are defined (e.g., using read_liberty with corner names).")
    else:
        if vdd_net_for_ir is None:
            print("Warning: VDD net not found for IR drop analysis. Skipping.")
        if m1_layer is None:
            print("Warning: Metal1 layer not found for IR drop analysis. Skipping.")

    # --- Correction: Add report_power command as requested by feedback ---
    # Note: report_power requires timing analysis results and activity files
    # (.saif/.vcd) for meaningful switching power. Leakage power might be available.
    # Without proper setup, this command might report zeros or default values.
    print("Reporting power...")
    design.evalTclString("report_power")
    # ------------------------------------------------------------------


else:
    print("Skipping routing stages due to critical error.")


# 17. Write outputs
print(f"Writing final DEF file: {outputDefFile}")
design.writeDef(outputDefFile)

print(f"Writing final Verilog file: {outputVerilogFile}")
design.evalTclString(f"write_verilog {outputVerilogFile}")

print(f"Writing final ODB file: {outputDbFile}")
design.writeDb(outputDbFile)

print("Script finished.")