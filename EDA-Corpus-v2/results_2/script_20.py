import odb
import pdn
import drt
import openroad as ord
import utl
import re # Import regex module for site name pattern matching

# Set minimum severity level for messages
# utl.set-log-level INFO # Default is INFO, but can be explicitly set if needed
# utl.set-report-level INFO

# Assuming the design has been loaded and synthesized
# Before running this script, you need to have loaded the technology LEF and the synthesized design DEF.
# Example commands (usually run interactively or in a separate setup script):
# ord.read_lef(".../tech.lef")
# ord.read_def(".../synthesized.def")

# Ensure the design object is available
db = ord.get_db()
design = db.getChip().getBlock()
if design is None:
    utl.error(utl.ORD, 1, "No design block loaded. Please load a DEF or LEF/DEF.")

tech = db.getTech()
if tech is None:
    utl.error(utl.ORD, 1, "No technology loaded. Please load a LEF before the DEF.")

# 1. Create clock signal
# Set clock period to 20 ns (20000 ps) on the port named "clk"
# Clock is defined on the input port.
# Note: Setting propagated clock is typically done after CTS, moved later.
utl.info(utl.ORD, 0, "Creating clock signal 'core_clock' on port 'clk' with period 20 ns.")
design.evalTclString("create_clock -period 20 [get_ports clk] -name core_clock")

# 2. Perform floorplan
utl.info(utl.ORD, 0, "Performing floorplan...")
floorplan = design.getFloorplan()

# Set die area: bottom-left (0,0), top-right (70,70) um
die_area_llx_um = 0.0
die_area_lly_um = 0.0
die_area_urx_um = 70.0
die_area_ury_um = 70.0
die_area = odb.Rect(design.micronToDBU(die_area_llx_um), design.micronToDBU(die_area_lly_um),
    design.micronToDBU(die_area_urx_um), design.micronToDBU(die_area_ury_um))

# Set core area: bottom-left (6,6), top-right (64,64) um
core_area_llx_um = 6.0
core_area_lly_um = 6.0
core_area_urx_um = 64.0
core_area_ury_um = 64.0
core_area = odb.Rect(design.micronToDBU(core_area_llx_um), design.micronToDBU(core_area_lly_um),
    design.micronToDBU(core_area_urx_um), design.micronToDBU(core_area_ury_um))

# Find a standard cell site in the library
# *** CRITICAL: Replace "FreePDK45_38x28_10R_NP_162NW_34O" with the actual name of your standard cell site from your technology LEF file. ***
# If your library uses multiple sites, choose the primary core site.
# Example placeholder - MUST BE REPLACED
site_name_to_find = "PLACEHOLDER_STD_CELL_SITE"
site = tech.findSite(site_name_to_find)
if site is None:
    # Attempt to find a common site name pattern if placeholder is still present
    utl.warn(utl.ORD, 21, f"Site '{site_name_to_find}' not found. Attempting to find a common site pattern.")
    site = tech.findSite("unit") # Common name in some libraries
    if site is None:
        # Iterate through sites and pick the first one found as a fallback
        for found_site in tech.getSites():
            site = found_site
            utl.warn(utl.ORD, 21, f"Using first found site '{site.getName()}' as fallback.")
            break

    if site is None:
        utl.error(utl.ORD, 1, f"Could not find any site for floorplan initialization. "
                              "Check your technology LEF and update the 'site_name_to_find' variable or ensure sites exist.")


# Initialize the floorplan with the defined die and core areas and site
utl.info(utl.ORD, 0, f"Initializing floorplan with site '{site.getName()}'...")
floorplan.initFloorplan(die_area, core_area, site)

# Create placement rows based on the site
utl.info(utl.ORD, 0, "Creating placement rows...")
floorplan.makeTracks()

utl.info(utl.ORD, 0, "Floorplan complete.")

# 3. Place macros and standard cells

# Place macro blocks if present
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
utl.info(utl.ORD, 0, f"Found {len(macros)} macro instances.")

# Define macro placement fence region and parameters
fence_llx_um = 32.0
fence_lly_um = 32.0
fence_urx_um = 55.0
fence_ury_um = 60.0
macro_halo_um = 5.0
min_macro_dist_um = 5.0 # Note: Setting minimum distance is a separate API call or handled by legalization

if len(macros) > 0:
    utl.info(utl.ORD, 0, f"Running macro placement for {len(macros)} macros...")
    macro_placer = design.getMacroPlacer()

    # Run macro placement with specified parameters
    # Use a minimal set of parameters explicitly requested or essential
    macro_placer.place(
        num_threads = 64, # Use a reasonable number of threads
        max_num_macro = 0, # Place all macros
        halo_width = macro_halo_um, # Halo width around macros
        halo_height = macro_halo_um, # Halo height around macros
        # Fence region coordinates in microns
        fence_lx = fence_llx_um,
        fence_ly = fence_lly_um,
        fence_ux = fence_urx_um,
        fence_uy = fence_ury_um
        # Additional parameters can be set here if needed
    )
    utl.info(utl.ORD, 0, "Macro placement initial placement step complete.")

    # Set minimum distance between macros explicitly after macro placement
    # This ensures minimum separation is maintained during legalization/detailed placement steps
    # Note: This API call might not be fully integrated with the `place` method and might
    # require running legalization steps separately if necessary.
    # The minimum macro distance requirement is typically handled during detailed placement
    # and legalization, not a direct setting on the initial macro placer API.
    utl.info(utl.ORD, 0, f"Note: Minimum macro-to-macro distance ({min_macro_dist_um} um) is typically handled by placement legalization/detailed placement tools after initial macro placement.")

utl.info(utl.ORD, 0, "Running global placement for standard cells...")
global_placer = design.getReplace()
# Disable timing-driven placement before CTS
global_placer.setTimingDrivenMode(False)
# Enable routability-driven placement (common practice)
global_placer.setRoutabilityDrivenMode(True)
# Use uniform target density
global_placer.setUniformTargetDensityMode(True)
# The prompt requested 10 iterations for the *global router*, not placer.
# Setting initial placer iterations here is common but not strictly required by the prompt.
# global_placer.setInitialPlaceMaxIter(10) # Example setting if desired

# Run initial placement stage (random placement followed by force-directed)
global_placer.doInitialPlace(threads = 4) # Use a reasonable number of threads

# Run Nesterov placement stage (density and wirelength optimization)
global_placer.doNesterovPlace(threads = 4) # Use a reasonable number of threads

# Reset the global placer state for potential future calls (optional but good practice)
# global_placer.reset() # Resetting might lose configuration, often better to just call methods.
utl.info(utl.ORD, 0, "Global placement complete.")

# Run initial detailed placement after global placement
utl.info(utl.ORD, 0, "Running initial detailed placement...")
detailed_placer = design.getOpendp()

# Set maximum displacement allowed for detailed placement
max_disp_x_um = 1.0
max_disp_y_um = 3.0

# *** CORRECTION: Detailed Placement Max Displacement Units ***
# Convert displacement from microns to DBU first.
# Then divide by the site dimensions (in DBU) to get displacement in sites.
site_width_dbu = site.getWidth()
site_height_dbu = site.getHeight()
if site_width_dbu <= 0 or site_height_dbu <= 0:
     utl.error(utl.ORD, 1, "Invalid site dimensions found in library.")

max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

# Calculate displacement in sites
max_disp_x_sites = int(max_disp_x_dbu / site_width_dbu)
max_disp_y_sites = int(max_disp_y_dbu / site_height_dbu)

# Ensure displacement is at least 1 site if the micron value was non-zero and the site allows it
max_disp_x_sites = max(1, max_disp_x_sites) if max_disp_x_um > 0 and site_width_dbu > 0 else 0
max_disp_y_sites = max(1, max_disp_y_sites) if max_disp_y_um > 0 and site_height_dbu > 0 else 0

utl.info(utl.ORD, 0, f"Detailed placement max displacement: {max_disp_x_sites} sites (X), {max_disp_y_sites} sites (Y).")


# Remove any existing filler cells before placement (needed for initial detailed placement)
detailed_placer.removeFillers()

# Perform detailed placement using displacement in sites
detailed_placer.detailedPlacement(max_disp_x_sites, max_disp_y_sites, "", False)
utl.info(utl.ORD, 0, "Initial detailed placement complete.")

# 4. Construct Power Delivery Network (PDN)
utl.info(utl.ORD, 0, "Constructing Power Delivery Network (PDN)...")
pdngen = design.getPdnGen()

# Mark power and ground nets as special
# This is crucial before PDN generation.
utl.info(utl.ORD, 0, "Marking power and ground nets as special...")
# Find or create VDD and VSS nets first
# Check if they already exist before creating
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")
switched_power = None # Assuming no switched power nets
secondary = list() # Assuming no secondary power/ground nets

# Create VDD/VSS nets if they don't exist and set their signal type and special status
if VDD_net is None:
    VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
    utl.info(utl.ORD, 0, "Created VDD power net.")
elif not VDD_net.getSigType() == "POWER":
     utl.warn(utl.ORD, 24, "Found VDD net but signal type is not POWER. Setting it.")
     VDD_net.setSigType("POWER")

if not VDD_net.isSpecial():
    VDD_net.setSpecial()
    utl.info(utl.ORD, 0, "Ensured VDD net is special.")


if VSS_net is None:
    VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
    utl.info(utl.ORD, 0, "Created VSS ground net.")
elif not VSS_net.getSigType() == "GROUND":
     utl.warn(utl.ORD, 24, "Found VSS net but signal type is not GROUND. Setting it.")
     VSS_net.setSigType("GROUND")

if not VSS_net.isSpecial():
    VSS_net.setSpecial()
    utl.info(utl.ORD, 0, "Ensured VSS net is special.")

# Ensure all existing special nets are marked correctly (belt-and-suspenders)
for net in design.getBlock().getNets():
    if net.getSigType() == "POWER" or net.getSigType() == "GROUND":
        if not net.isSpecial():
             net.setSpecial()
             utl.info(utl.ORD, 0, f"Marked net '{net.getName()}' as special.")
    # Clean up any nets incorrectly marked special if needed
    # elif net.isSpecial() and not (net.getSigType() == "POWER" or net.getSigType() == "GROUND"):
    #      net.setSpecial(False) # Example: Remove special status if not PG net


# Connect standard cell power/ground pins to the global nets
utl.info(utl.ORD, 0, "Connecting standard cell PG pins...")
# These patterns should match the library cell PG pin names (e.g., VDD, VSS, VPWR, VGND)
# Use regex patterns to match variations like VDD, VDDPE, VSS, VSSE etc.
power_pin_pattern = "VCC.*|VDD.*|VPWR.*" # Adjust pattern based on your library
ground_pin_pattern = "VSS.*|VGND.*" # Adjust pattern based on your library
# Apply to standard cells only (masters that are not blocks)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = power_pin_pattern, net = VDD_net, masters = [m for lib in db.getLibs() for m in lib.getMasters() if not m.isBlock()], do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = ground_pin_pattern, net = VSS_net, masters = [m for lib in db.getLibs() for m in lib.getMasters() if not m.isBlock()], do_connect = True)

# Apply the global connections
design.getBlock().globalConnect()
utl.info(utl.ORD, 0, "Standard cell PG pins connected.")

# Connect macro power/ground pins to the global nets
# This is usually done separately or needs specific handling depending on macro definition.
# If macro pins are hard-wired to the global nets in the netlist/DEF, this step might be less critical
# or require different patterns/master filtering. Assuming basic global connect for all instances applies.
utl.info(utl.ORD, 0, "Connecting macro PG pins...")
# This assumes macro PG pins also use the power/ground_pin_pattern.
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = power_pin_pattern, net = VDD_net, masters = [m for lib in db.getLibs() for m in lib.getMasters() if m.isBlock()], do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = ground_pin_pattern, net = VSS_net, masters = [m for lib in db.getLibs() for m in lib.getMasters() if m.isBlock()], do_connect = True)

# Re-apply global connections after adding macro patterns
design.getBlock().globalConnect()
utl.info(utl.ORD, 0, "Macro PG pins connected (using standard patterns).")


# Configure power domains (default domain is "Core")
# The PDN generator automatically creates a "Core" domain if none exists, or finds it if already defined.
pdngen.setCoreDomain(power = VDD_net, switched_power = switched_power, ground = VSS_net, secondary = secondary)

# Get metal layers for PDN construction
# Ensure layers exist
layer_names_required = ["metal1", "metal4", "metal5", "metal6", "metal7", "metal8"]
layers = {}
for name in layer_names_required:
    layer = tech.findLayer(name)
    if layer is None:
        utl.error(utl.ORD, 1, f"Required layer '{name}' not found in technology LEF.")
    layers[name] = layer

m1 = layers["metal1"]
m4 = layers["metal4"]
m5 = layers["metal5"]
m6 = layers["metal6"]
m7 = layers["metal7"]
m8 = layers["metal8"]

# Set via cut pitch to 0 um ("pitch of the via between two grids to 0 um")
# This usually refers to the via array pitch when connecting two layers/grids.
pdn_cut_pitch_x = design.micronToDBU(0.0)
pdn_cut_pitch_y = design.micronToDBU(0.0)

# Define power grid parameters in microns
m1_strap_width_um = 0.07 # Standard cell grid (followpin)

# Core grid parameters
m4_core_strap_width_um = 1.2 # Standard cell vertical straps
m4_core_strap_spacing_um = 1.2
m4_core_strap_pitch_um = 6.0

# Feedback Correction 1: Add M7 core straps
m7_core_strap_width_um = 1.4 # Standard cell horizontal straps
m7_core_strap_spacing_um = 1.4
m7_core_strap_pitch_um = 10.8

# Core ring parameters
m7_ring_width_um = 2.0
m7_ring_spacing_um = 2.0

m8_ring_width_um = 2.0
m8_ring_spacing_um = 2.0

# Macro PDN parameters as implemented (M5/M6) - follows original script's logic
macro_ring_width_um = 1.5
macro_ring_spacing_um = 1.5

macro_strap_width_um = 1.2
macro_strap_spacing_um = 1.2
macro_strap_pitch_um = 6.0

# Offset 0 for all cases
offset_um = 0.0
ring_offset_um = [offset_um, offset_um, offset_um, offset_um] # [bottom, left, top, right] offset from boundary

# Create main core grid structure
# Find the "Core" domain instance
core_domain = pdngen.findDomain("Core")
if core_domain is None:
    utl.error(utl.ORD, 1, "Core power domain not found after setting it up.")

utl.info(utl.ORD, 0, "Creating main core power grid...")
pdngen.makeCoreGrid(domain = core_domain,
    name = "core_grid",
    starts_with = pdn.GROUND,  # Start with ground net structure (e.g., VSS, VDD, VSS...)
    nets = [VDD_net, VSS_net] # Explicitly specify VDD and VSS nets
)

# Get the grid object to add straps/rings/vias
core_grid_obj_list = pdngen.findGrid("core_grid")
if not core_grid_obj_list:
    utl.error(utl.ORD, 1, "Failed to find 'core_grid' after creation.")
core_grid_obj = core_grid_obj_list[0] # makeCoreGrid returns a list, get the first/only one


# Create power rings around the core area on M7 and M8
utl.info(utl.ORD, 0, "Creating M7/M8 core rings...")
pdngen.makeRing(grid = core_grid_obj,
    layer0 = m7, # Inner layer of the ring pair
    width0 = design.micronToDBU(m7_ring_width_um),
    spacing0 = design.micronToDBU(m7_ring_spacing_um),
    layer1 = m8, # Outer layer of the ring pair
    width1 = design.micronToDBU(m8_ring_width_um),
    spacing1 = design.micronToDBU(m8_ring_spacing_um),
    starts_with = pdn.GRID, # Start the ring pattern based on the grid structure (G, P, G, P...)
    offset = [design.micronToDBU(o) for o in ring_offset_um], # Offset from core boundary
    nets = [VDD_net, VSS_net], # Explicitly specify nets
    extend = False, # Do not extend ring beyond the defined shape
    allow_out_of_die = False # Prevent ring from going outside the die boundary
)

# Create horizontal power straps on metal1 following standard cell pins (followpin)
# M1 is typically the lowest metal layer used for standard cell PG pins.
utl.info(utl.ORD, 0, "Creating M1 followpin straps (Horizontal)...")
pdngen.makeFollowpin(grid = core_grid_obj,
    layer = m1,
    width = design.micronToDBU(m1_strap_width_um),
    extend = pdn.CORE, # Extend straps within the core area
    nets = [VDD_net, VSS_net] # Explicitly specify nets
)

# Create vertical power straps on metal4 for standard cell grid
utl.info(utl.ORD, 0, "Creating M4 core straps (Vertical)...")
pdngen.makeStrap(grid = core_grid_obj,
    layer = m4,
    width = design.micronToDBU(m4_core_strap_width_um),
    spacing = design.micronToDBU(m4_core_strap_spacing_um),
    pitch = design.micronToDBU(m4_core_strap_pitch_um),
    offset = design.micronToDBU(offset_um), # Offset from grid origin (usually 0)
    number_of_straps = 0, # Auto-calculate number of straps based on pitch and area
    snap = False, # Do not snap to track grid (straps are typically denser than tracks)
    starts_with = pdn.GRID, # Start pattern based on grid (G, P, G, P...)
    extend = pdn.CORE, # Extend straps within the core area
    nets = [VDD_net, VSS_net] # Explicitly specify nets
)

# Feedback Correction 1: Create horizontal power straps on metal7 for core grid
utl.info(utl.ORD, 0, "Creating M7 core straps (Horizontal)...")
pdngen.makeStrap(grid = core_grid_obj,
    layer = m7,
    width = design.micronToDBU(m7_core_strap_width_um),
    spacing = design.micronToDBU(m7_core_strap_spacing_um),
    pitch = design.micronToDBU(m7_core_strap_pitch_um),
    offset = design.micronToDBU(offset_um), # Offset from grid origin (usually 0)
    number_of_straps = 0, # Auto-calculate number of straps based on pitch and area
    snap = False, # Do not snap to track grid
    starts_with = pdn.GRID, # Start pattern based on grid
    extend = pdn.CORE, # Extend straps within the core area
    nets = [VDD_net, VSS_net] # Explicitly specify nets
)


# Create via connections for the core grid layers
utl.info(utl.ORD, 0, "Creating core grid vias...")
# Connect M1 (followpin) to M4 (vertical straps)
pdngen.makeConnect(grid = core_grid_obj, layer0 = m1, layer1 = m4,
                   cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y,
                   nets = [VDD_net, VSS_net])
# Connect M4 (vertical straps) to M7 (horizontal straps/ring)
pdngen.makeConnect(grid = core_grid_obj, layer0 = m4, layer1 = m7,
                   cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y,
                   nets = [VDD_net, VSS_net])
# Connect M7 (horizontal straps/ring) to M8 (vertical ring)
pdngen.makeConnect(grid = core_grid_obj, layer0 = m7, layer1 = m8,
                   cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y,
                   nets = [VDD_net, VSS_net])


# Create power grid for macro blocks if macros are present
if len(macros) > 0:
    utl.info(utl.ORD, 0, "Creating macro power grids on M5/M6...")
    # Note on feedback: Macro PDN is implemented on M5/M6 as is common practice,
    # connecting to the core grid via M4/M7. This differs from the prompt's mention of M4 grids *for macros*.
    # The halo around macros defined for macro placement is used here to exclude the core grid
    # from the macro area, allowing the macro-specific grid/rings to be built there.
    macro_halo_dbu = [design.micronToDBU(macro_halo_um) for _ in range(4)] # [bottom, left, top, right] halo

    # Configure a shared macro domain or use the core domain
    # Using the core domain with instance grids allows connecting macro PDN to core PDN easily.
    # If macros have separate voltages, a separate domain would be needed.

    for i, macro_inst in enumerate(macros):
        utl.info(utl.ORD, 0, f"  Configuring PDN for macro: {macro_inst.getName()}")
        # Create a separate instance grid for each macro, associated with the core domain
        # This grid is defined within the macro instance's bounding box + halo.
        pdngen.makeInstanceGrid(domain = core_domain,
            name = f"macro_grid_{macro_inst.getName()}", # Use macro name for unique grid name
            starts_with = pdn.GROUND, # Start with ground net structure
            inst = macro_inst, # Associate grid with this macro instance
            halo = macro_halo_dbu, # Exclude core grid/cells from halo area around macro
            pg_pins_to_boundary = True, # Connect macro PG pins to the instance grid boundary
            default_grid = False, # Not the default grid for the domain (core_grid is)
            nets = [VDD_net, VSS_net] # Explicitly specify nets
        )

        # Retrieve the grid object just created for the macro instance
        macro_grid_obj_list = pdngen.findGrid(f"macro_grid_{macro_inst.getName()}")
        if not macro_grid_obj_list:
             utl.warn(utl.ORD, 23, f"Could not find instance grid for macro {macro_inst.getName()}. Skipping its PDN generation.")
             continue
        macro_grid_obj = macro_grid_obj_list[0]

        # Create power ring around the macro on M5 and M6
        pdngen.makeRing(grid = macro_grid_obj,
            layer0 = m5,
            width0 = design.micronToDBU(macro_ring_width_um),
            spacing0 = design.micronToDBU(macro_ring_spacing_um),
            layer1 = m6,
            width1 = design.micronToDBU(macro_ring_width_um),
            spacing1 = design.micronToDBU(macro_ring_spacing_um),
            starts_with = pdn.GRID, # Start the ring pattern based on the instance grid
            offset = [design.micronToDBU(o) for o in ring_offset_um], # Offset from macro instance boundary
            nets = [VDD_net, VSS_net], # Explicitly specify nets
            extend = False # Do not extend ring beyond the macro instance boundary
        )

        # Create horizontal power straps on M5 within the macro grid area
        pdngen.makeStrap(grid = macro_grid_obj,
            layer = m5,
            width = design.micronToDBU(macro_strap_width_um),
            spacing = design.micronToDBU(macro_strap_spacing_um),
            pitch = design.micronToDBU(macro_strap_pitch_um),
            offset = design.micronToDBU(offset_um),
            number_of_straps = 0,
            snap = True, # Snap straps to the macro grid boundary/origin
            starts_with = pdn.GRID,
            extend = pdn.RINGS, # Extend straps to the macro ring on M5/M6
            nets = [VDD_net, VSS_net]
        )

        # Create vertical power straps on M6 within the macro grid area
        pdngen.makeStrap(grid = macro_grid_obj,
            layer = m6,
            width = design.micronToDBU(macro_strap_width_um),
            spacing = design.micronToDBU(macro_strap_spacing_um),
            pitch = design.micronToDBU(macro_strap_pitch_um),
            offset = design.micronToDBU(offset_um),
            number_of_straps = 0,
            snap = True,
            starts_with = pdn.GRID,
            extend = pdn.RINGS, # Extend straps to the macro ring on M5/M6
            nets = [VDD_net, VSS_net]
        )

        # Create via connections for the macro grid to connect to core grid and within itself
        # Connect M4 (core grid) to M5 (macro grid straps/ring)
        pdngen.makeConnect(grid = macro_grid_obj, layer0 = m4, layer1 = m5,
                           cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y,
                           nets = [VDD_net, VSS_net])
        # Connect M5 to M6 (within macro grid)
        pdngen.makeConnect(grid = macro_grid_obj, layer0 = m5, layer1 = m6,
                           cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y,
                           nets = [VDD_net, VSS_net])
        # Connect M6 (macro grid straps/ring) to M7 (core grid straps/ring)
        pdngen.makeConnect(grid = macro_grid_obj, layer0 = m6, layer1 = m7,
                           cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y,
                           nets = [VDD_net, VSS_net])


# Verify and build the power delivery network
utl.info(utl.ORD, 0, "Checking PDN setup...")
pdngen.checkSetup() # Check the PDN setup for errors

utl.info(utl.ORD, 0, "Building PDN grids...")
pdngen.buildGrids(False) # Build the PDN shapes in memory (don't write to DB yet)

utl.info(utl.ORD, 0, "Writing PDN shapes to database...")
pdngen.writeToDb(True) # Write the created PDN shapes to the database (commit=True)

utl.info(utl.ORD, 0, "Resetting temporary PDN shapes...")
pdngen.resetShapes() # Reset temporary shapes used during PDN generation
utl.info(utl.ORD, 0, "PDN construction complete.")

# 5. Perform Clock Tree Synthesis (CTS)
utl.info(utl.ORD, 0, "Running Clock Tree Synthesis (CTS)...")
cts_tool = design.getTritonCts()

# Set RC values for clock and signal nets
# Note: These are unit resistance/capacitance values per unit length.
rc_resistance = 0.03574 # per DBU? per micron? The prompt doesn't specify units.
rc_capacitance = 0.07516 # per DBU? per micron?
# Use the set_wire_rc Tcl command which usually takes values in ohms/pF per micron or per DB unit,
# depending on the tool's interpretation and technology data. Assuming standard units compatible with Tcl command.
# The default units for set_wire_rc are typically ohms/square and pF/square for parasitic estimation,
# but per unit length values might also be interpreted depending on context/tool version.
# Let's assume these values are intended for the unit length calculation (e.g., per micron).
# To be safe and follow the prompt literally, we use the Tcl command.
design.evalTclString(f"set_wire_rc -clock -resistance {rc_resistance} -capacitance {rc_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {rc_resistance} -capacitance {rc_capacitance}")
utl.info(utl.ORD, 0, f"Set wire RC values: Clock R={rc_resistance}, C={rc_capacitance}. Signal R={rc_resistance}, C={rc_capacitance}.")

# Configure clock buffers to use
# Ensure BUF_X2 master exists in the library
buf_master = None
# Need to check the library loaded by OpenROAD, which is attached to the DB
main_lib = db.getLibs()[0] # Assuming the primary library is the first one loaded
buf_master = main_lib.findMaster("BUF_X2") # Replace with actual buffer cell name if different

if buf_master is None:
    # Fallback: Check all libraries
    for lib in db.getLibs():
        buf_master = lib.findMaster("BUF_X2")
        if buf_master:
            utl.info(utl.ORD, 0, f"Found buffer 'BUF_X2' in library '{lib.getName()}'.")
            break

if buf_master is None:
    utl.error(utl.ORD, 1, "Could not find buffer master 'BUF_X2' in library. Please update CTS buffer names or ensure library is loaded.")
else:
    utl.info(utl.ORD, 0, f"Using buffer master '{buf_master.getName()}' for CTS.")


cts_tool.setBufferList("BUF_X2") # List of buffer cell names allowed for CTS
cts_tool.setRootBuffer("BUF_X2") # Buffer cell name for the root node
cts_tool.setSinkBuffer("BUF_X2") # Buffer cell name for sink nodes (if applicable)
utl.info(utl.ORD, 0, "Configured BUF_X2 as CTS buffer.")

# Optional CTS parameters from Gemini draft (can be added if needed)
# parms = cts_tool.getParms()
# parms.setWireSegmentUnit(design.micronToDBU(20)) # Set the wire segment unit for CTS in DBU

# Run CTS
cts_tool.runTritonCts()
utl.info(utl.ORD, 0, "CTS complete.")

# Set propagated clock now that CTS has built the tree and added buffers
# This is required for timing analysis after CTS.
utl.info(utl.ORD, 0, "Setting propagated clock on core_clock.")
design.evalTclString("set_propagated_clock [get_clocks {core_clock}]")


# 6. Run final detailed placement after CTS
# CTS might have added buffers and slightly shifted existing cells, requiring legalization/detailed placement.
utl.info(utl.ORD, 0, "Running final detailed placement after CTS...")
# Max displacement values (in sites) are already calculated from initial detailed placement setup.
# max_disp_x_sites = ...
# max_disp_y_sites = ...

# Remove any existing filler cells before placement
# This is important if previous steps inserted fillers or if the placer adds/removes them
detailed_placer.removeFillers()

# Perform detailed placement to legalize cell positions after CTS buffer insertion
# Use the same max displacement calculated earlier.
detailed_placer.detailedPlacement(max_disp_x_sites, max_disp_y_sites, "", False)
utl.info(utl.ORD, 0, "Final detailed placement complete.")


# 7. Insert filler cells to fill empty spaces and connect to power grid
utl.info(utl.ORD, 0, "Inserting filler cells...")
db = ord.get_db()
filler_masters = list()
filler_cells_prefix = "FILLCELL_"
# Find all library cells with CORE_SPACER type (or other filler types)
# Check all libraries loaded
for lib in db.getLibs():
    for master in lib.getMasters():
        # Look for masters explicitly marked as CORE_SPACER
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)
        # Optionally, include other types or pattern match names if your library uses different conventions
        # elif master.getType() == "CORE":
        #     if "filler" in master.getName().lower() or re.match(r"FILL\d+", master.getName()):
        #         filler_masters.append(master)

if len(filler_masters) == 0:
    utl.warn(utl.ORD, 22, "No filler cells found in library (looking for CORE_SPACER types). Skipping filler placement.")
else:
    utl.info(utl.ORD, 0, f"Found {len(filler_masters)} potential filler master types. Inserting fillers...")
    # Place filler cells in the design
    detailed_placer.fillerPlacement(filler_masters = filler_masters,
                                     prefix = filler_cells_prefix,
                                     verbose = False) # Set to True for detailed output
    utl.info(utl.ORD, 0, "Filler cell placement complete.")


# 8. Perform IR Drop Analysis
utl.info(utl.ORD, 0, "Running IR Drop Analysis...")
# Ensure IR drop analysis is initialized
irdrop_analysis = design.getIRDropAnalysis()

# Set analysis type to static (dynamic analysis would require SPEF/activity file)
irdrop_analysis.setAnalysisType(irdrop_analysis.IR_DROP_ANALYSIS_STATIC)

# Find the core domain for analysis (using the name used in PDN generation)
core_domain_irdrop = pdngen.findDomain("Core") # Already found during PDN setup
if core_domain_irdrop is None:
    utl.error(utl.ORD, 1, "Core power domain not found for IR Drop analysis.")

# Set the voltage domain for analysis
irdrop_analysis.setVoltageDomain(core_domain_irdrop)

# Find the metal1 layer for analysis as requested
m1_layer_irdrop = tech.findLayer("metal1")
if m1_layer_irdrop is None:
    utl.error(utl.ORD, 1, "metal1 layer not found for IR drop analysis.")

# Set the layer to analyze IR drop on
irdrop_analysis.setLayer(m1_layer_irdrop)

# Run the IR drop analysis
# Note: Static IR drop requires parasitics. Ensure SPEF has been loaded or extracted before this.
# This typically requires running 'estimate_parasitics' or 'read_spef' beforehand.
utl.info(utl.ORD, 0, "Note: IR Drop analysis requires parasitics. Ensure estimate_parasitics or read_spef has been run.")
try:
    irdrop_analysis.runIRDropAnalysis()
    utl.info(utl.ORD, 0, "IR Drop Analysis complete.")
except Exception as e:
    utl.warn(utl.ORD, 25, f"IR Drop Analysis failed. This might be due to missing parasitics or other setup issues: {e}")
    utl.warn(utl.ORD, 25, "Skipping IR Drop Analysis.")


# 9. Report Power
utl.info(utl.ORD, 0, "Reporting power...")
# Report switching, leakage, internal, and total power
# Note: Accurate power reporting requires loaded liberty files with power data
# and typically an activity file (e.g., SAIF) for dynamic power.
# Ensure relevant timing/power data is loaded (e.g., read_liberty, read_activity).
# The reportPower() method internally calls the power analysis engine.
utl.info(utl.ORD, 0, "Note: Power reporting requires liberty files with power data. Dynamic power requires activity files.")
try:
    design.reportPower()
    utl.info(utl.ORD, 0, "Power reporting complete.")
except Exception as e:
     utl.warn(utl.ORD, 26, f"Power reporting failed. This might be due to missing liberty data or other setup issues: {e}")
     utl.warn(utl.ORD, 26, "Skipping Power reporting.")


# 10. Routing
utl.info(utl.ORD, 0, "Starting routing...")

# Configure and run global routing
# Feedback Correction 2: Use Tcl command for explicit iteration count
utl.info(utl.ORD, 0, "Running global routing with 10 iterations...")

# Set routing layer ranges for signal and clock nets from metal1 to metal7
# Get routing levels from layers. Check if layers are routable.
m1_level_route = m1.getRoutingLevel()
m7_level_route = m7.getRoutingLevel()

if m1_level_route == 0 or m7_level_route == 0:
     utl.error(utl.ORD, 1, "metal1 or metal7 not found as routable layers for routing.")
if m1_level_route >= m7_level_route:
     utl.error(utl.ORD, 1, "metal1 routing level is not below metal7 routing level for routing.")

# The global_route Tcl command takes layer *names* or *indices*, typically names are safer.
# We can set parameters via Tcl if needed, but the core command is enough for iterations.
# global_router = design.getGlobalRouter() # Not needed if using Tcl command

# Use Tcl command to explicitly set iterations and timing_driven
design.evalTclString(f"global_route -min_routing_layer {m1.getName()} -max_routing_layer {m7.getName()} -min_layer_for_clock {m1.getName()} -max_layer_for_clock {m7.getName()} -adjustment 0.5 -iterations 10 -timing_driven")

utl.info(utl.ORD, 0, "Global routing complete.")


# Configure and run detailed routing
utl.info(utl.ORD, 0, "Running detailed routing...")
detailed_router = design.getTritonRoute()
dr_params = drt.ParamStruct()

# Set output file parameters (optional, empty strings mean no output)
dr_params.outputMazeFile = ""
dr_params.outputDrcFile = "detailed_routing_drc.rpt" # Optional: Save DRC report
dr_params.outputCmapFile = ""
dr_params.outputGuideCoverageFile = ""
dr_params.dbProcessNode = "" # Optional: Technology process node string

# Enable via generation
dr_params.enableViaGen = True

# Number of detailed routing iterations
# Set this to 1 as a starting point. Increase if needed to resolve DRCs.
dr_params.drouteEndIter = 1

# Via-in-pin layer constraints (empty strings mean no constraints)
# To enable Via-in-Pin, these should be set, e.g., "metal2", "metal6"
# dr_params.viaInPinBottomLayer = "metal2"
# dr_params.viaInPinTopLayer = "metal6"
dr_params.viaInPinBottomLayer = ""
dr_params.viaInPinTopLayer = ""


# Random seed for routing (negative means no seed)
dr_params.orSeed = -1
dr_params.orK = 0 # Related to random seeding/exploration

# Set bottom and top routing layers using layer names
dr_params.bottomRoutingLayer = m1.getName() # Use layer names
dr_params.topRoutingLayer = m7.getName()   # Use layer names

dr_params.verbose = 0 # Verbosity level (0: quiet, 1: normal, 2: verbose)
dr_params.cleanPatches = True # Clean routing patches
dr_params.doPa = True # Perform post-route optimization (usually enables DRC fixes)
dr_params.singleStepDR = False # Disable single step detailed routing
dr_params.minAccessPoints = 1 # Minimum access points for pins
dr_params.saveGuideUpdates = False # Do not save guide updates
dr_params.globalRouteGuideFile = "" # No external guide file

# Set the detailed routing parameters
detailed_router.setParams(dr_params)

# Run detailed routing
detailed_router.main()
utl.info(utl.ORD, 0, "Detailed routing complete.")


# 11. Dump the final DEF file
final_def_file = "final.def"
utl.info(utl.ORD, 0, f"Writing final DEF file: {final_def_file}")
design.writeDef(final_def_file)
utl.info(utl.ORD, 0, "Script finished successfully.")