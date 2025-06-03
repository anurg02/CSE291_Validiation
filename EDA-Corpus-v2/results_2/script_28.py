from openroad import Tech, Design, Timing
from pathlib import Path
import odb
import pdn
import drt
import psm
import openroad as ord
import sys

# Initialize OpenROAD objects
tech = Tech()

# --- Script Setup ---
# Set paths to library and design files
# Adjust these paths based on your OpenROAD installation and design data
# It's good practice to handle missing directories
libDir = Path("../Design/nangate45/lib")
lefDir = Path("../Design/nangate45/lef")
designDir = Path("../Design/")
design_top_module_name = "gcd" # Replace with your top module name

# Check if directories exist
if not libDir.is_dir():
    print(f"Error: Library directory not found: {libDir}")
    sys.exit(1)
if not lefDir.is_dir():
    print(f"Error: LEF directory not found: {lefDir}")
    sys.exit(1)
if not designDir.is_dir():
    print(f"Error: Design directory not found: {designDir}")
    sys.exit(1)


# Read all liberty (.lib) and LEF files from the library directories
# It's generally best practice to load technology LEF first, then cell LEFs.
# Assuming technology LEF files have ".tech.lef" in their name.
lefFiles = sorted(list(lefDir.glob('*.lef')), key=lambda x: '.tech' not in x.name)

if not lefFiles:
    print(f"Error: No LEF files found in {lefDir}")
    sys.exit(1)

# Load technology and cell LEF files
for lefFile in lefFiles:
    print(f"Reading LEF: {lefFile.as_posix()}")
    tech.readLef(lefFile.as_posix())

libFiles = list(libDir.glob("*.lib"))
if not libFiles:
    print(f"Error: No Liberty files found in {libDir}")
    sys.exit(1)

# Load liberty timing libraries
for libFile in libFiles:
    print(f"Reading Liberty: {libFile.as_posix()}")
    tech.readLiberty(libFile.as_posix())

# Create design and read Verilog netlist
verilogFile = designDir/str(design_top_module_name + ".v") # Assuming netlist is named after top module
if not verilogFile.is_file():
    print(f"Error: Verilog file not found: {verilogFile}")
    sys.exit(1)

design = Design(tech)
print(f"Reading Verilog: {verilogFile.as_posix()}")
design.readVerilog(verilogFile.as_posix())

# Link the design to the loaded libraries
print(f"Linking design: {design_top_module_name}")
design.link(design_top_module_name)

if not design.getBlock():
    print("Error: Design block not created after linking. Check verilog top module name and library files.")
    sys.exit(1)

# --- Timing Constraints ---
# Configure clock constraints
clock_period_ns = 40.0 # 40 ns period
port_name = "clk" # Assuming clock port is named 'clk'
clock_name = "core_clock" # Clock domain name

print(f"Setting clock constraint: Period {clock_period_ns} ns on port '{port_name}'")
# Create clock signal on the specified port
# Use get_ports to ensure the port exists
if not design.evalTclString(f"get_ports {{{port_name}}}"):
     print(f"Error: Clock port '{port_name}' not found.")
     # Attempt to proceed without clock if not critical for flow, or exit
     # Exiting is safer for timing-dependent steps later
     sys.exit(1)

design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {port_name}] -name {clock_name}")
# Propagate the clock signal throughout the design
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# --- Floorplan ---
print("Performing floorplan...")
# Initialize floorplan with specified die and core areas
floorplan = design.getFloorplan()

# Set die area bounding box from (0,0) to (60,50) um
die_area_lx = 0.0
die_area_ly = 0.0
die_area_ux = 60.0
die_area_uy = 50.0
die_area = odb.Rect(design.micronToDBU(die_area_lx), design.micronToDBU(die_area_ly),
    design.micronToDBU(die_area_ux), design.micronToDBU(die_area_uy))

# Set core area bounding box from (8,8) to (52,42) um
core_area_lx = 8.0
core_area_ly = 8.0
core_area_ux = 52.0
core_area_uy = 42.0
core_area = odb.Rect(design.micronToDBU(core_area_lx), design.micronToDBU(core_area_ly),
    design.micronToDBU(core_area_ux), design.micronToDBU(core_area_uy))

# Find a suitable site (Assuming a common site name like FreePDK45 from examples)
# You might need to check your LEF files or tech file for the correct site name.
# Iterate through available sites and pick the first valid one if the specific one fails
site = None
site_name_candidates = ["FreePDK45_38x28_10R_NP_162NW_34O", "CORE_SITE"] # Add more potential names
for name in site_name_candidates:
    site = floorplan.findSite(name)
    if site:
        print(f"Using site: {site.getName()}")
        break

if not site:
    # Attempt to find any site if specific ones are not found
    print("Specific site names not found. Trying to find any site...")
    for s in design.getTech().getDB().getTech().getSites():
         site = s
         print(f"Using first found site: {site.getName()}")
         break

if not site:
     print("Error: No sites found in technology file!")
     sys.exit(1)

# Initialize floorplan with defined die and core areas and the selected site
print(f"Initializing floorplan with die {die_area_lx},{die_area_ly} to {die_area_ux},{die_area_uy} um and core {core_area_lx},{core_area_ly} to {core_area_ux},{core_area_uy} um")
floorplan.initFloorplan(die_area, core_area, site)
# Generate routing tracks based on the technology and floorplan
floorplan.makeTracks()
print("Floorplan complete.")

# --- Placement ---
print("Performing placement...")

# Place macro blocks if present
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]
if len(macros) > 0:
    print(f"Placing {len(macros)} macros...")
    mpl = design.getMacroPlacer()
    block = design.getBlock()

    # Define the macro fence region from (18,12) to (43,42) um
    macro_fence_lx = 18.0
    macro_fence_ly = 12.0
    macro_fence_ux = 43.0
    macro_fence_uy = 42.0

    # Set halo width and height around macros (5 um)
    macro_halo_width_um = 5.0
    macro_halo_height_um = 5.0

    # Set minimum spacing between macros (5 um) - Correction based on feedback implied requirement
    macro_gap_x_um = 5.0
    macro_gap_y_um = 5.0

    # Set the layer for macro pin snapping (metal4 is common)
    # Ensure metal4 exists in your technology
    db = ord.get_db()
    tech_db = db.getTech()
    m4_layer_for_snap = tech_db.findLayer("metal4")
    macro_snap_layer = m4_layer_for_snap.getRoutingLevel() if m4_layer_for_snap else None # Use layer level or None
    if not m4_layer_for_snap:
        print("Warning: metal4 layer not found for macro pin snapping. Snapping disabled.")
        macro_snap_layer = None


    print(f"Macro fence: {macro_fence_lx},{macro_fence_ly} to {macro_fence_ux},{macro_fence_uy} um")
    print(f"Macro halo: {macro_halo_width_um} um")
    print(f"Macro gap: {macro_gap_x_um} um in X, {macro_gap_y_um} um in Y")

    # Run macro placement
    # Using parameters from prompt and converting to DBU where necessary
    mpl.place(
        num_threads = 64, # Use multiple threads
        halo_width = design.micronToDBU(macro_halo_width_um),
        halo_height = design.micronToDBU(macro_halo_height_um),
        fence_lx = design.micronToDBU(macro_fence_lx),
        fence_ly = design.micronToDBU(macro_fence_ly),
        fence_ux = design.micronToDBU(macro_fence_ux),
        fence_uy = design.micronToDBU(macro_fence_uy),
        macro_gap = [design.micronToDBU(macro_gap_x_um), design.micronToDBU(macro_gap_y_um)], # Added macro gap constraint
        snap_layer = macro_snap_layer
        # Other parameters will use default values
    )
    print("Macro placement complete.")
else:
    print("No macros found. Skipping macro placement.")


# Configure and run global placement for standard cells
print("Performing global placement...")
gpl = design.getReplace()
# Basic global placement settings
gpl.setTimingDrivenMode(False) # Assuming no timing libraries loaded for timing-driven placement yet
gpl.setRoutabilityDrivenMode(True)
gpl.setUniformTargetDensityMode(True)
# Set maximum initial placement iterations
gpl.setInitialPlaceMaxIter(10)
gpl.setInitDensityPenalityFactor(0.05)
# Perform initial and Nesterov global placement
gpl.doInitialPlace(threads = 4)
gpl.doNesterovPlace(threads = 4)
gpl.reset() # Reset placer state for next stage
print("Global placement complete.")

# Run initial detailed placement after global placement
print("Performing initial detailed placement...")
opendp = design.getOpendp()
# Remove temporary filler cells if any were inserted by global placer (optional, but good practice)
opendp.removeFillers()
# Define maximum allowed displacement (1 um in X, 3 um in Y)
max_disp_x_um = 1.0
max_disp_y_um = 3.0
max_disp_x = int(design.micronToDBU(max_disp_x_um))
max_disp_y = int(design.micronToDBU(max_disp_y_um))
print(f"Detailed placement max displacement: {max_disp_x_um} um in X, {max_disp_y_um} um in Y")

# Perform detailed placement
# The last argument (incremental) can be False for initial DP
opendp.detailedPlacement(max_disp_x, max_disp_y, "", False)
print("Initial detailed placement complete.")

# --- Power Delivery Network (PDN) Construction ---
print("Constructing power delivery network...")
pdngen = design.getPdnGen()
block = design.getBlock()

# Set up global power/ground connections for standard cells and macros
print("Setting up global power/ground nets...")
# Find existing power and ground nets or create if needed
VDD_net = block.findNetByName("VDD") # Use findNetByName for robustness
VSS_net = block.findNetByName("VSS")
if VDD_net is None:
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSigType("POWER")
    print("Created VDD net.")
if VSS_net is None:
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSigType("GROUND")
    print("Created VSS net.")

# Mark power/ground nets as special nets (required for PDN generation)
VDD_net.setSpecial()
VSS_net.setSpecial()

# Connect standard cell power pins to global VDD/VSS nets
# Ensure pin patterns match your library (e.g., VDD, VSS, VPWR, VGND)
print("Connecting standard cell PG pins...")
# Use addGlobalConnect with specific nets
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
# Apply the global connections
block.globalConnect()

# Set core voltage domain with primary power/ground nets
pdngen.setCoreDomain(power = VDD_net, switched_power = None, ground = VSS_net, secondary = [])

# Get necessary metal layers for PDN construction and routing
db = ord.get_db()
tech_db = db.getTech()
required_layers = ["metal1", "metal2", "metal3", "metal4", "metal5", "metal6", "metal7", "metal8"]
found_layers = {}
missing_layers = []
for layer_name in required_layers:
    layer = tech_db.findLayer(layer_name)
    if layer:
        found_layers[layer_name] = layer
        print(f"Found layer: {layer_name}")
    else:
        missing_layers.append(layer_name)

if missing_layers:
     print(f"Error: Required metal layers not found: {', '.join(missing_layers)}")
     print("Please check your technology LEF file.")
     sys.exit(1)

# Assign found layers to variables for easier access
m1 = found_layers["metal1"]
m2 = found_layers["metal2"]
m3 = found_layers["metal3"]
m4 = found_layers["metal4"]
m5 = found_layers["metal5"]
m6 = found_layers["metal6"]
m7 = found_layers["metal7"]
m8 = found_layers["metal8"]

# Assign routing layer levels for router
m1_level = m1.getRoutingLevel()
m7_level = m7.getRoutingLevel()


# Set via cut pitch for connections between layers (0 um as requested)
# Note: A non-zero pitch is usually required for correct via generation in PDN.
# Setting to 0 might cause issues depending on the tool version and tech file rules.
pdn_cut_pitch_x_um = 0.0
pdn_cut_pitch_y_um = 0.0
pdn_cut_pitch = [design.micronToDBU(pdn_cut_pitch_x_um), design.micronToDBU(pdn_cut_pitch_y_um)]
print(f"PDN via cut pitch set to: {pdn_cut_pitch_x_um} um (Note: 0 pitch may cause issues)")

# Create core grid for standard cells
# This grid will cover the core area defined in floorplan
print("Making core grid for standard cells and macros...")
domains = [pdngen.findDomain("Core")]
if not domains or domains[0] is None:
    print("Error: Core domain not found.")
    sys.exit(1)

for domain in domains:
    # Create the main core grid structure definition
    pdngen.makeCoreGrid(domain = domain,
        name = "stdcell_macro_grid", # Renamed grid to reflect it covers both
        starts_with = pdn.GROUND, # Start grid pattern with ground (VSS)
        pin_layers = [], # No specific pin layers needed to start grid
        generate_obstructions = [], # Do not generate obstructions
        powercell = None, # No power cell defined
        powercontrol = None # No power control network defined
    )

grid_list = pdngen.findGrid("stdcell_macro_grid")
if not grid_list:
    print("Error: Core grid not found after definition.")
    sys.exit(1)
core_grid = grid_list[0] # Assume only one core grid

# Add rings, straps, and connections to the core grid definition
print("Adding rings and straps to core grid...")

# Create power rings around core area using metal7 and metal8
ring_width_um = 5.0
ring_spacing_um = 5.0
ring_offset_um = 0.0 # 0 um offset from core boundary
ring_offset = [design.micronToDBU(ring_offset_um) for i in range(4)]
# Get all routing layers for potential connection to pads/ports
ring_connect_to_pad_layers = [layer for layer in tech_db.getLayers() if layer.getType() == "ROUTING"]
pdngen.makeRing(grid = core_grid,
    layer0 = m7, width0 = design.micronToDBU(ring_width_um), spacing0 = design.micronToDBU(ring_spacing_um), # M7 ring properties
    layer1 = m8, width1 = design.micronToDBU(ring_width_um), spacing1 = design.micronToDBU(ring_spacing_um), # M8 ring properties
    starts_with = pdn.GRID, # Start pattern from the grid definition
    offset = ring_offset, # Offset from core boundary
    pad_offset = [design.micronToDBU(0) for i in range(4)], # Pad offset (0 um as requested)
    extend = False, # Do not extend beyond ring boundary (default behavior)
    pad_pin_layers = ring_connect_to_pad_layers, # Layers for pad/port connections
    nets = [], # Connect all nets in the domain (VDD, VSS)
    allow_out_of_die = True) # Allow rings to extend out of die if needed
print(f"Added rings on {m7.getName()}/{m8.getName()} with width {ring_width_um} um and spacing {ring_spacing_um} um.")

# Create horizontal power straps on metal1 following cell pin pattern (for standard cells)
m1_strap_width_um = 0.07
pdngen.makeFollowpin(grid = core_grid,
    layer = m1, # M1 layer
    width = design.micronToDBU(m1_strap_width_um), # Strap width
    extend = pdn.CORE) # Extend to core boundary
print(f"Added followpin straps on {m1.getName()} with width {m1_strap_width_um} um.")

# Create power straps on metal4 (for standard cells and macros as per prompt)
m4_strap_width_um = 1.2
m4_strap_spacing_um = 1.2
m4_strap_pitch_um = 6.0
pdngen.makeStrap(grid = core_grid,
    layer = m4, width = design.micronToDBU(m4_strap_width_um), spacing = design.micronToDBU(m4_strap_spacing_um), pitch = design.micronToDBU(m4_strap_pitch_um), # Strap dimensions
    offset = design.micronToDBU(0), # 0 um offset
    number_of_straps = 0, # Auto-calculate number of straps
    snap = False, # Do not snap to grid (default) - can be True if snapping desired
    starts_with = pdn.GRID, # Start pattern from grid definition
    extend = pdn.CORE, # Extend to core boundary
    nets = []) # Connect all nets in domain
print(f"Added straps on {m4.getName()} with width {m4_strap_width_um} um, spacing {m4_strap_spacing_um} um, pitch {m4_strap_pitch_um} um.")

# Create power straps on metal7 and metal8 (parallel to rings, within core)
# Note: The prompt requests M7/M8 for rings *and* straps. This structure might be redundant
# or requires careful consideration of starts_with/extend options.
# Using 'extend = pdn.RINGS' or 'extend = pdn.CORE' seems reasonable for straps within the core.
# 'starts_with = pdn.GRID' ensures they align with the core grid definition.
m7_m8_strap_width_um = 1.4
m7_m8_strap_spacing_um = 1.4
m7_m8_strap_pitch_um = 10.8
pdngen.makeStrap(grid = core_grid,
    layer = m7, width = design.micronToDBU(m7_m8_strap_width_um), spacing = design.micronToDBU(m7_m8_strap_spacing_um), pitch = design.micronToDBU(m7_m8_strap_pitch_um), # Strap dimensions
    offset = design.micronToDBU(0), # 0 um offset
    number_of_straps = 0, # Auto-calculate number of straps
    snap = False,
    starts_with = pdn.GRID,
    extend = pdn.CORE, # Extend to core boundary
    nets = [])
print(f"Added straps on {m7.getName()} with width {m7_m8_strap_width_um} um, spacing {m7_m8_strap_spacing_um} um, pitch {m7_m8_strap_pitch_um} um.")

pdngen.makeStrap(grid = core_grid,
    layer = m8, width = design.micronToDBU(m7_m8_strap_width_um), spacing = design.micronToDBU(m7_m8_strap_spacing_um), pitch = design.micronToDBU(m7_m8_strap_pitch_um), # Strap dimensions
    offset = design.micronToDBU(0), # 0 um offset
    number_of_straps = 0, # Auto-calculate number of straps
    snap = False,
    starts_with = pdn.GRID,
    extend = pdn.CORE, # Extend to core boundary
    nets = [])
print(f"Added straps on {m8.getName()} with width {m7_m8_strap_width_um} um, spacing {m7_m8_strap_spacing_um} um, pitch {m7_m8_strap_pitch_um} um.")


# Create power grid elements for macro blocks if they exist
if len(macros) > 0:
    print("Adding power grid elements for macros on M5 and M6...")

    m5_m6_strap_width_um = 1.2
    m5_m6_strap_spacing_um = 1.2
    m5_m6_strap_pitch_um = 6.0

    # Add M5 straps covering the core area where macros are placed
    pdngen.makeStrap(grid = core_grid, # Add to the main core grid
        layer = m5, width = design.micronToDBU(m5_m6_strap_width_um), spacing = design.micronToDBU(m5_m6_strap_spacing_um), pitch = design.micronToDBU(m5_m6_strap_pitch_um),
        offset = design.micronToDBU(0),
        number_of_straps = 0,
        snap = False, # Snap to grid for regular pattern
        starts_with = pdn.GRID,
        extend = pdn.CORE, # Extend to core boundary
        nets = [] # Connect all nets in domain
        # No 'instances' filter here, assuming M5/M6 grid covers macro areas within core
    )
    print(f"Added straps on {m5.getName()} with width {m5_m6_strap_width_um} um, spacing {m5_m6_strap_spacing_um} um, pitch {m5_m6_strap_pitch_um} um.")

    # Add M6 straps covering the core area where macros are placed
    pdngen.makeStrap(grid = core_grid, # Add to the main core grid
        layer = m6, width = design.micronToDBU(m5_m6_strap_width_um), spacing = design.micronToDBU(m5_m6_strap_spacing_um), pitch = design.micronToDBU(m5_m6_strap_pitch_um),
        offset = design.micronToDBU(0),
        number_of_straps = 0,
        snap = False, # Snap to grid for regular pattern
        starts_with = pdn.GRID,
        extend = pdn.CORE, # Extend to core boundary
        nets = [] # Connect all nets in domain
        # No 'instances' filter here, assuming M5/M6 grid covers macro areas within core
    )
    print(f"Added straps on {m6.getName()} with width {m5_m6_strap_width_um} um, spacing {m5_m6_strap_spacing_um} um, pitch {m5_m6_strap_pitch_um} um.")


# Add connections between relevant layers used in the grid.
# Via cut pitch is set to 0 as requested.
# Note: A non-zero pitch is usually required for correct via generation.
print("Adding connections for PDN grid...")
# Connect M1 to M2 (assuming M1 straps are horizontal, M2 might be vertical in this tech)
# The connects should align with the orientation of the layers they connect.
# If M1 is horizontal and M2 is vertical, you need connects that bridge H and V layers.
# Assuming this tech has alternating layers, e.g., M1 H, M2 V, M3 H, etc.
# Connect M1 (H) to M2 (V)
pdngen.makeConnect(grid = core_grid, layer0 = m1, layer1 = m2, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
print(f"Added connects between {m1.getName()} and {m2.getName()} with pitch {pdn_cut_pitch_x_um} um.")
# Connect M2 (V) to M3 (H)
pdngen.makeConnect(grid = core_grid, layer0 = m2, layer1 = m3, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
print(f"Added connects between {m2.getName()} and {m3.getName()} with pitch {pdn_cut_pitch_x_um} um.")
# Connect M3 (H) to M4 (V)
pdngen.makeConnect(grid = core_grid, layer0 = m3, layer1 = m4, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
print(f"Added connects between {m3.getName()} and {m4.getName()} with pitch {pdn_cut_pitch_x_um} um.")
# Connect M4 (V) to M5 (H)
pdngen.makeConnect(grid = core_grid, layer0 = m4, layer1 = m5, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
print(f"Added connects between {m4.getName()} and {m5.getName()} with pitch {pdn_cut_pitch_x_um} um.")
# Connect M5 (H) to M6 (V)
pdngen.makeConnect(grid = core_grid, layer0 = m5, layer1 = m6, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
print(f"Added connects between {m5.getName()} and {m6.getName()} with pitch {pdn_cut_pitch_x_um} um.")
# Connect M6 (V) to M7 (H)
pdngen.makeConnect(grid = core_grid, layer0 = m6, layer1 = m7, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
print(f"Added connects between {m6.getName()} and {m7.getName()} with pitch {pdn_cut_pitch_x_um} um.")
# Connect M7 (H) to M8 (V)
pdngen.makeConnect(grid = core_grid, layer0 = m7, layer1 = m8, cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1])
print(f"Added connects between {m7.getName()} and {m8.getName()} with pitch {pdn_cut_pitch_x_um} um.")

# Verify PDN setup
print("Checking PDN setup...")
pdngen.checkSetup()
# Build the defined power grids (This generates the physical shapes)
print("Building grids...")
pdngen.buildGrids(False) # False means do not write immediately to DB
# Write the created power grid shapes to the design database
print("Writing grids to DB...")
pdngen.writeToDb(True) # True means clear temporary shapes after writing
print("PDN construction complete.")


# --- Clock Tree Synthesis (CTS) ---
print("Performing Clock Tree Synthesis...")
# Ensure propagated clock is set before CTS
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Set unit resistance and capacitance values for clock and signal nets
# These values affect the RC extraction used internally by CTS and routing tools.
wire_r_per_micron = 0.03574
wire_c_per_micron = 0.07516
print(f"Setting wire RC: R={wire_r_per_micron}/um, C={wire_c_per_micron}/um")
design.evalTclString(f"set_wire_rc -clock -resistance {wire_r_per_micron} -capacitance {wire_c_per_micron}")
design.evalTclString(f"set_wire_rc -signal -resistance {wire_r_per_micron} -capacitance {wire_c_per_micron}")

cts = design.getTritonCts()
# Set wire segment unit length (used in tree building). Example value in DBU.
# A common value is related to standard cell width or site width. Using an absolute value for simplicity.
parms = cts.getParms()
# Convert desired micron length (e.g., 5 um) to DBU
cts_wire_segment_um = 5.0
parms.setWireSegmentUnit(design.micronToDBU(cts_wire_segment_um))
print(f"CTS wire segment unit set to: {cts_wire_segment_um} um")


# Configure clock buffers to use
# Ensure BUF_X2 master exists in your library
buffer_cell_name = "BUF_X2"
# Verify the buffer cell exists
db = ord.get_db()
buffer_master = None
for lib in db.getLibs():
    buffer_master = lib.findMaster(buffer_cell_name)
    if buffer_master:
        break

if not buffer_master:
    print(f"Error: Buffer cell '{buffer_cell_name}' not found in libraries.")
    sys.exit(1)

print(f"Setting CTS buffers to: {buffer_cell_name}")
cts.setBufferList(buffer_cell_name)
cts.setRootBuffer(buffer_cell_name) # Set root buffer
cts.setSinkBuffer(buffer_cell_name) # Set sink buffer

# Run clock tree synthesis
cts.runTritonCts()
print("Clock Tree Synthesis complete.")

# --- Detailed Placement (Post-CTS) ---
print("Performing detailed placement after CTS...")
# Detailed placement cleans up any displacement caused by CTS buffer insertion.
# Remove any previously inserted fillers before re-running DP
# No fillers are inserted yet, so removeFillers is not strictly needed but safe.
opendp.removeFillers() # Remove any fillers inserted by previous steps
# Define maximum allowed displacement again (same as before, 1 um X, 3 um Y)
# max_disp_x and max_disp_y are already calculated
# Perform detailed placement incrementally this time
opendp.detailedPlacement(max_disp_x, max_disp_y, "", True) # Use True for incremental DP after CTS
print("Detailed placement after CTS complete.")

# --- Filler Cell Insertion ---
print("Inserting filler cells...")
db = ord.get_db()
filler_masters = list()
filler_cells_prefix = "FILLCELL_" # Naming convention for filler cells
# Find all CORE_SPACER type cells in the library
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

# If filler cells are found, perform filler placement
if len(filler_masters) == 0:
    print("No CORE_SPACER filler cells found in library!")
else:
    # Sort fillers by size (smallest first is common practice for opendp)
    filler_masters.sort(key=lambda m: m.getWidth() * m.getHeight())
    print(f"Found {len(filler_masters)} filler cell types. Inserting fillers...")
    opendp.fillerPlacement(filler_masters = filler_masters,
                           prefix = filler_cells_prefix,
                           verbose = False)
    print("Filler cell insertion complete.")


# --- Routing ---
print("Performing routing...")

# Configure and run global routing
print("Performing global routing...")
grt = design.getGlobalRouter()
# Set the minimum and maximum routing layers for signal and clock nets
# Layers M1 to M7 as requested
grt.setMinRoutingLayer(m1_level)
grt.setMaxRoutingLayer(m7_level)
grt.setMinLayerForClock(m1_level) # Use same layers for clock routing
grt.setMaxLayerForClock(m7_level)
# Set adjustment factor for congestion (higher value means less capacity)
grt.setAdjustment(0.5) # Example value, tune based on congestion
grt.setVerbose(True) # Enable verbose output
# Set global router iterations (30 times as requested)
grt.setIterations(30)
print(f"Global router iterations set to {grt.getIterations()}")
# Run global routing. True enables internal rip-up/reroute for congestion.
grt.globalRoute(True)
print("Global routing complete.")

# Configure and run detailed routing
print("Performing detailed routing...")
drter = design.getTritonRoute()
# Set detailed routing parameters
params = drt.ParamStruct()
# Set bottom and top routing layers (M1 to M7 as requested)
params.bottomRoutingLayer = m1.getName()
params.topRoutingLayer = m7.getName()
# Set other parameters (using example values or defaults)
params.outputMazeFile = "" # Optional debug output
params.outputDrcFile = "triton_route_drc.rpt" # Output DRC violations
params.outputCmapFile = ""
params.outputGuideCoverageFile = ""
params.dbProcessNode = "" # Set if using process node specific rules
params.enableViaGen = True
params.drouteEndIter = 1 # Number of detailed routing iterations (typically 1-3)
# Via in pin layers should generally cover the range of routing layers used for pins
# If pins are only on lower layers (e.g., M1, M2), adjust accordingly
params.viaInPinBottomLayer = m1.getName()
params.viaInPinTopLayer = m7.getName()
params.orSeed = -1 # Random seed (-1 means unseeded)
params.orK = 0 # Optional, related to guide optimization
params.verbose = 1
params.cleanPatches = True # Clean up routing patches
params.doPa = True # Perform post-route antenna fixing
params.singleStepDR = False
params.minAccessPoints = 1 # Minimum access points for pins
params.saveGuideUpdates = False # Save guide updates during DR

drter.setParams(params)
# Run detailed routing
drter.main()
print("Detailed routing complete.")

# --- Analysis ---
print("Performing IR drop analysis...")
psm_obj = design.getPDNSim()
timing = Timing(design) # Get timing object for corners

# Define source types for power grid analysis
# Options include FULL, STRAPS, BUMPS. Analyzing based on STRAPS is common for core.
source_types = [psm.GeneratedSourceType_FULL, psm.GeneratedSourceType_STRAPS, psm.GeneratedSourceType_BUMPS]

# Ensure a timing corner is available
corners = timing.getCorners()
if not corners:
    print("Warning: No timing corners found. Skipping IR drop analysis.")
else:
    # Analyze the VDD power net's static IR drop
    # The report will include analysis on all connected layers, including M1 as requested.
    print(f"Analyzing IR drop on net '{VDD_net.getName()}' using corner '{corners[0].getName()}'")
    psm_obj.analyzePowerGrid(net = VDD_net, # Analyze the VDD net
        enable_em = False, # Disable electromigration analysis (prompt only asked for IR drop)
        corner = corners[0], # Use the first timing corner found
        use_prev_solution = False, # Do not use previous solution
        em_file = "irdrop_em.rpt", # EM report file path (even if EM is off)
        error_file = "irdrop.errors", # Error report file path
        voltage_source_file = "irdrop.vol", # Voltage source report file path
        voltage_file = "irdrop.rpt", # Voltage drop report file path
        source_type = source_types[1]) # Use STRAPS as source type (common for core analysis)

    print("IR drop analysis complete. Report saved to irdrop.rpt")

# --- Power Reporting (Added based on verification feedback) ---
print("Reporting power...")
# The verification feedback requested a power report (switching, internal, leakage).
# The 'report_power' Tcl command provides this. Note that for accurate switching
# and internal power, activity data (like a VCD file) and complete timing updates
# are usually required, which are not included in this script flow. Leakage power
# may be reported based on the library and timing corner.
try:
    design.evalTclString("report_power -file power.rpt")
    print("Power report generated: power.rpt")
except Exception as e:
    print(f"Warning: Could not generate power report. Ensure timing is updated and activity data is available if needed. Error: {e}")


# --- Output ---
# Dump the final DEF file after detailed routing as requested
output_def_file = "final.def"
print(f"Writing final DEF file: {output_def_file}")
design.writeDef(output_def_file)

# Save the final OpenDB file (optional but recommended)
output_odb_file = "final.odb"
print(f"Writing final ODB file: {output_odb_file}")
design.writeDb(output_odb_file)

print("Script finished.")