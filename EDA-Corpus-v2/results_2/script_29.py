# This script consolidates and verifies Python code for OpenROAD,
# performing physical design steps based on a given prompt.

# Add necessary imports
from openroad import Tech, Design, Timing
from pathlib import Path
import odb
import pdn
import mpl
import drt
import openroad as ord
import sys # For stdout redirection

# 1. OpenROAD Initialization and Configuration
# Initialize OpenROAD environment
ord.init()

# Optional: Redirect stdout for logging OpenROAD messages
# You can uncomment the lines below to redirect to a file
# try:
#     log_file = open("openroad.log", "w")
#     ord.redirect_stdout(log_file)
# except IOError:
#     print("WARNING: Could not open log file for writing.")

print("OpenROAD initialized.")

# Initialize OpenROAD objects (Tech is usually obtained via ord.get_tech() after init)
tech = ord.get_tech()

# Set paths to library and design files
# !!! IMPORTANT: Update these paths to match your actual file locations !!!
# Example relative paths based on a common OpenROAD tutorial structure
libDir = Path("../Design/nangate45/lib")
lefDir = Path("../Design/nangate45/lef")
designDir = Path("../Design/")

# Assuming the Verilog file is named 'design.v' or similar and top module is 'top'
# Update these variables based on your actual design files
verilog_file_name = "design.v"
design_top_module_name = "top"
site_name = "FreePDK45_38x28_10R_NP_162NW_34O" # Update site name from your LEF if necessary
clock_port_name = "clk" # Update this to match your clock port name in Verilog
clock_name = "core_clock" # Internal name for the clock net
vdd_net_name = "VDD" # Update if your VDD net is named differently in Verilog
vss_net_name = "VSS" # Update if your VSS net is named differently in Verilog

# Check if directories exist
if not libDir.exists():
    print(f"ERROR: Library directory not found: {libDir}")
    ord.finish()
    sys.exit(1)
if not lefDir.exists():
    print(f"ERROR: LEF directory not found: {lefDir}")
    ord.finish()
    sys.exit(1)
if not designDir.exists():
     print(f"ERROR: Design directory not found: {designDir}")
     ord.finish()
     sys.exit(1)
if not (designDir / verilog_file_name).exists():
    print(f"ERROR: Verilog file not found: {designDir / verilog_file_name}")
    ord.finish()
    sys.exit(1)


print(f"Reading technology files from {lefDir}")
# Read all liberty (.lib) and LEF files from the library directories
# Use list() to consume generators if needed later, or iterate directly
libFiles = sorted(list(libDir.glob("*.lib"))) # Sort for deterministic order
techLefFiles = sorted(list(lefDir.glob("*.tech.lef")))
lefFiles = sorted(list(lefDir.glob('*.lef')))

# Load technology and cell LEF files first
for techLefFile in techLefFiles:
    print(f"Reading LEF file: {techLefFile}")
    tech.readLef(techLefFile.as_posix())
for lefFile in lefFiles:
    print(f"Reading LEF file: {lefFile}")
    tech.readLef(lefFile.as_posix())

print(f"Reading liberty files from {libDir}")
# Load liberty timing libraries
for libFile in libFiles:
    print(f"Reading Liberty file: {libFile}")
    tech.readLiberty(libFile.as_posix())

# Create design and read Verilog netlist
print(f"Reading Verilog file: {designDir / verilog_file_name}")
design = Design(tech)
verilogFile = designDir / verilog_file_name
design.readVerilog(verilogFile.as_posix())

# Link the design to resolve module references and create the block
print(f"Linking design with top module: {design_top_module_name}")
design.link(design_top_module_name)

# Get the block object and database pointers after linking
block = design.getBlock()
db = ord.get_db() # Get the database object
tech_db = db.getTech() # Get the tech object from the database


# 2. Set Clock Constraints
clock_period_ns = 40
print(f"Setting clock period {clock_period_ns} ns on port {clock_port_name}")
# Create clock signal using the standard Tcl API for consistency and full features
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
# Propagate the clock signal for accurate timing analysis after placement/CTS
print(f"Setting propagated clock for '{clock_name}'")
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")


# 3. Floorplan
print("Performing floorplan...")
floorplan = design.getFloorplan()
site = floorplan.findSite(site_name)
if not site:
    print(f"ERROR: Site '{site_name}' not found in the technology LEF files.")
    print("Please check your LEF files and update the site_name variable.")
    # Exit gracefully if a critical element like the site is missing
    ord.finish()
    sys.exit(1)
print(f"Using site: {site.getName()}")

# Set die area bottom-left at (0,0) and top-right at (45um, 45um)
die_lx_um = 0.0
die_ly_um = 0.0
die_ux_um = 45.0
die_uy_um = 45.0
die_lx = design.micronToDBU(die_lx_um)
die_ly = design.micronToDBU(die_ly_um)
die_ux = design.micronToDBU(die_ux_um)
die_uy = design.micronToDBU(die_uy_um)
die_area = odb.Rect(die_lx, die_ly, die_ux, die_uy)
print(f"Die area: ({die_lx_um},{die_ly_um})um to ({die_ux_um},{die_uy_um})um")

# Set core area bottom-left at (5um, 5um) and top-right at (40um, 40um)
core_lx_um = 5.0
core_ly_um = 5.0
core_ux_um = 40.0
core_uy_um = 40.0
core_lx = design.micronToDBU(core_lx_um)
core_ly = design.micronToDBU(core_ly_um)
core_ux = design.micronToDBU(core_ux_um)
core_uy = design.micronToDBU(core_uy_um)
core_area = odb.Rect(core_lx, core_ly, core_ux, core_uy)
print(f"Core area: ({core_lx_um},{core_ly_um})um to ({core_ux_um},{core_uy_um})um")

# Initialize floorplan with the specified areas and site
floorplan.initFloorplan(die_area, core_area, site)
# Make routing tracks based on the floorplan site and technology
floorplan.makeTracks()
print("Floorplan initialized and tracks created.")

# Dump DEF after floorplanning
floorplan_def_file = "floorplan.def"
print(f"Dumping DEF after floorplan: {floorplan_def_file}")
design.writeDef(floorplan_def_file)


# 4. Configure Global Power/Ground Connections
print("Configuring global power/ground connections...")
# Find existing power and ground nets or create if needed
VDD_net = block.findNet(vdd_net_name)
VSS_net = block.findNet(vss_net_name)
switched_power = None # Set this if using switched power domains
secondary = list() # Add secondary power nets if needed

# Create VDD/VSS nets if they don't exist in the netlist (common for top-level nets)
if VDD_net is None:
    print(f"Net {vdd_net_name} not found, creating special power net.")
    VDD_net = odb.dbNet_create(block, vdd_net_name)
    VDD_net.setSpecial()
    VDD_net.setSigType("POWER")
if VSS_net is None:
    print(f"Net {vss_net_name} not found, creating special ground net.")
    VSS_net = odb.dbNet_create(block, vss_net_name)
    VSS_net.setSpecial()
    VSS_net.setSigType("GROUND")

# Connect standard cell power/ground pins to the respective global nets
# Update pin patterns if necessary for your library (e.g., VDD, VSS, VDDPE, VDDCE, VSSE)
# Using general patterns that cover common naming conventions
print(f"Adding global connect for {vdd_net_name} (patterns: ^VDD.*$) and {vss_net_name} (patterns: ^VSS.*$)")
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VDD.*$", net=VDD_net, do_connect=True)
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VSS.*$", net=VSS_net, do_connect=True)

# Apply the global connections to the design database
block.globalConnect()
print("Global power/ground connections configured.")


# 5. Place Macros (if any)
print("Placing macros...")
# Identify macro instances (instances whose master is a block)
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]
if len(macros) > 0:
    print(f"Found {len(macros)} macro(s).")
    mplacer = design.getMacroPlacer()

    # Define macro placement parameters in microns and convert to DBU
    # Set a halo region around each macro as 5 um
    macro_halo_width_um = 5.0
    macro_halo_height_um = 5.0
    macro_halo_width_dbu = design.micronToDBU(macro_halo_width_um)
    macro_halo_height_dbu = design.micronToDBU(macro_halo_height_um)
    print(f"Setting macro halo: {macro_halo_width_um}um x {macro_halo_height_um}um ({macro_halo_width_dbu} x {macro_halo_height_dbu} DBU)")
    # Note: The 5um halo helps achieve minimum separation *between halo boundaries*.
    # The placer algorithm aims to prevent standard cells/routing from entering the halo
    # and tries to keep halos separated.

    # Set a fence region to place macros inside
    # bottom-left corner as 5 um,5 um, and the top-right corner as 20 um,25 um
    fence_lx_um = 5.0
    fence_ly_um = 5.0
    fence_ux_um = 20.0
    fence_uy_um = 25.0
    fence_lx_dbu = design.micronToDBU(fence_lx_um)
    fence_ly_dbu = design.micronToDBU(fence_ly_um)
    fence_ux_dbu = design.micronToDBU(fence_ux_um)
    fence_uy_dbu = design.micronToDBU(fence_uy_um)
    print(f"Setting macro fence region: ({fence_lx_um},{fence_ly_um})um to ({fence_ux_um},{fence_uy_um})um ({fence_lx_dbu},{fence_ly_dbu} to {fence_ux_dbu},{fence_uy_dbu} DBU)")

    # Layer for snapping macro pins to track grid (metal4 as requested)
    snap_layer_name = "metal4"
    snap_layer_db = tech_db.findLayer(snap_layer_name)
    if not snap_layer_db:
        print(f"ERROR: Snap layer '{snap_layer_name}' not found in technology DB.")
        ord.finish()
        sys.exit(1)
    snap_layer_level = snap_layer_db.getRoutingLevel()
    print(f"Snapping macro pins to {snap_layer_name} (level {snap_layer_level})")

    # Run macro placement algorithm
    # Using essential parameters like block, fence, halo, and snap_layer.
    # Other parameters control algorithm specifics and can be left as defaults or tuned.
    print("Running macro placement algorithm...")
    mplacer.place(
        block=block, # Pass the block object
        num_threads = 64, # Use multiple threads for potentially faster execution
        halo_width = macro_halo_width_dbu,
        halo_height = macro_halo_height_dbu,
        fence_lx = fence_lx_dbu,
        fence_ly = fence_ly_dbu,
        fence_ux = fence_ux_dbu,
        fence_uy = fence_uy_dbu,
        snap_layer = snap_layer_level,
        # Other parameters from mplacer.h can be added here for tuning if needed,
        # but are not strictly required by the prompt.
        # E.g., wirelength_weight, boundary_weight, guidance_weight, fence_weight, target_util
    )
    print("Macro placement complete.")
else:
    print("No macros found in the design. Skipping macro placement.")

# Dump DEF after macro placement (this happens whether macros were placed or not,
# reflecting their initial or placed locations).
macro_place_def_file = "macro_placement.def"
print(f"Dumping DEF after macro placement: {macro_place_def_file}")
design.writeDef(macro_place_def_file)


# 6. Global Placement
print("Performing global placement of standard cells...")
# Get the global placer object (Replace tool)
gpl = design.getReplace()

# Set placement modes
# Timing-driven mode can improve performance, but might increase runtime
# gpl.setTimingDrivenMode(True) # Uncomment to enable timing-driven placement
gpl.setTimingDrivenMode(False) # Keep as False based on prompt, adjust as needed
gpl.setRoutabilityDrivenMode(True) # Enable routability-driven placement to reduce congestion
gpl.setUniformTargetDensityMode(True) # Use a uniform target density across the core area

# Set number of iterations for initial placement
# Prompt instruction "Set the iteration of the global router as 30 times" likely refers to GP iterations.
gp_iterations = 30
print(f"Setting global placement initial iterations: {gp_iterations}")
gpl.setInitialPlaceMaxIter(gp_iterations)

# Perform initial placement (e.g., using bookshelf data or random)
print("Running initial global placement...")
gpl.doInitialPlace(threads=4) # Use multiple threads

# Perform Nesterov-based placement refinement (improves wirelength and density)
print("Running Nesterov placement refinement...")
gpl.doNesterovPlace(threads=4) # Use multiple threads

# Reset placer state (often done before subsequent stages)
gpl.reset()
print("Global placement complete.")

# Dump DEF after global placement
global_place_def_file = "global_placement.def"
print(f"Dumping DEF after global placement: {global_place_def_file}")
design.writeDef(global_place_def_file)


# 7. Detailed Placement (Initial - before CTS)
print("Performing initial detailed placement...")
# Get the detailed placer object (OpenDP tool)
opendp = design.getOpendp()

# Calculate maximum displacement in DBU based on microns
# Set the maximum displacement at the x-axis as 1 um, and the y-axis as 3 um
max_disp_x_um = 1.0
max_disp_y_um = 3.0
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)
print(f"Setting detailed placement max displacement: X={max_disp_x_um}um ({max_disp_x_dbu} DBU), Y={max_disp_y_um}um ({max_disp_y_dbu} DBU)")

# Run detailed placement to fix overlaps and align cells to rows/sites
# The last two parameters "" and False relate to specific modes/options not requested.
print("Running detailed placement...")
# Parameters: max_displacement_x, max_displacement_y, detailed_placement_type, debug_mode
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Initial detailed placement complete.")

# Dump DEF after initial detailed placement
initial_dp_def_file = "detailed_placement_before_cts.def"
print(f"Dumping DEF after initial detailed placement: {initial_dp_def_file}")
design.writeDef(initial_dp_def_file)


# 8. Set RC Values for Timing Analysis
print("Setting wire RC values for clock and signal nets...")
# These values are used by the static timing analyzer (STA)
# Set the unit resistance and the unit capacitance value for clock and signal wires to 0.03574 and 0.07516, respectively.
clock_resistance = 0.03574
clock_capacitance = 0.07516
signal_resistance = 0.03574
signal_capacitance = 0.07516

# Use the Tcl API to set these values as there's no direct Python API for this currently
design.evalTclString(f"set_wire_rc -clock -resistance {clock_resistance} -capacitance {clock_capacitance}")
print(f"Clock wire RC set: R={clock_resistance}, C={clock_capacitance}")

design.evalTclString(f"set_wire_rc -signal -resistance {signal_resistance} -capacitance {signal_capacitance}")
print(f"Signal wire RC set: R={signal_resistance}, C={signal_capacitance}")


# 9. Clock Tree Synthesis (CTS)
print("Performing clock tree synthesis...")
# Get the CTS tool object (TritonCts)
cts = design.getTritonCts()

# Set clock buffer cells to be used by CTS
# Set CTS with using BUF_X2 as clock buffers
buffer_cell = "BUF_X2" # Update this based on your library if necessary
# Find the buffer master in the library to ensure it exists
buffer_master = None
for lib in db.getLibs():
    if lib.getTech() == tech_db:
        buffer_master = lib.findMaster(buffer_cell)
        if buffer_master:
            break

if not buffer_master:
    print(f"ERROR: Clock buffer cell '{buffer_cell}' not found in the loaded libraries.")
    print("Please check your library files and update the buffer_cell variable.")
    ord.finish()
    sys.exit(1)

print(f"Setting CTS buffer cells to: {buffer_cell}")
cts.setBufferList(buffer_cell) # List of buffers allowed
cts.setRootBuffer(buffer_cell) # Specific buffer for the root
cts.setSinkBuffer(buffer_cell) # Specific buffer for sinks (leaf nodes)

# Additional CTS parameters can be set here if needed using cts.getParms() or other methods

# Run CTS on the designated clock network(s)
print("Running clock tree synthesis...")
# CTS typically operates on propagated clocks defined earlier
cts.runTritonCts()
print("Clock tree synthesis complete.")

# Dump DEF after CTS
cts_def_file = "cts.def"
print(f"Dumping DEF after CTS: {cts_def_file}")
design.writeDef(cts_def_file)


# 10. Detailed Placement (Final - after CTS)
print("Performing final detailed placement after CTS...")
# CTS can slightly move cells or insert new buffers, requiring a final detailed placement pass.
# Use the same maximum displacement limits as before CTS.
print(f"Running detailed placement with max displacement X={max_disp_x_um}um, Y={max_disp_y_um}um...")
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Final detailed placement complete.")

# Dump DEF after final detailed placement
final_dp_def_file = "detailed_placement_after_cts.def"
print(f"Dumping DEF after final detailed placement: {final_dp_def_file}") # Corrected typo here
design.writeDef(final_dp_def_file)


# 11. Power Delivery Network (PDN) Construction
print("Constructing Power Delivery Network...")
# Get the PDN generation tool object (PdnGen)
pdngen = design.getPdnGen()

# Define metal layers by name using the technology database object
m1 = tech_db.findLayer("metal1")
m4 = tech_db.findLayer("metal4")
m5 = tech_db.findLayer("metal5")
m6 = tech_db.findLayer("metal6")
m7 = tech_db.findLayer("metal7")
m8 = tech_db.findLayer("metal8")

# Check if all required layers were found
required_layers = {'metal1': m1, 'metal4': m4, 'metal5': m5, 'metal6': m6, 'metal7': m7, 'metal8': m8}
for name, layer in required_layers.items():
    if not layer:
        print(f"ERROR: Required metal layer '{name}' not found in technology DB.")
        ord.finish()
        sys.exit(1)

# Define via cut pitch (0 um as requested, means use technology default pitch)
# For makeConnect, cut_pitch_x/y=0 uses the via's default cut spacing.
# The prompt mentions "set the pitch of the via between two grids to 0 um",
# which is slightly ambiguous, but typically implies using the tech default or no specific override.
pdn_cut_pitch_um = 0.0
# Using 0 for DBU values will signal the tool to use the default via pitch from the tech file
pdn_cut_pitch_dbu = design.micronToDBU(pdn_cut_pitch_um) # This will be 0 if micron is 0
pdn_cut_pitch = [0, 0] # [pitch_x, pitch_y]. Explicitly setting to 0 will use via's default pitch
print(f"Setting PDN via cut pitch: {pdn_cut_pitch_um}um ({pdn_cut_pitch_dbu} DBU). Using tech default if 0.")

# Define offsets (0 um as requested)
offset_um = 0.0
offset_dbu = design.micronToDBU(offset_um)
# For makeRing pad_offset is a list [left, bottom, right, top], offset is a single value
# For makeStrap offset is a single value
pad_offset = [offset_dbu, offset_dbu, offset_dbu, offset_dbu]
print(f"Setting PDN offset: {offset_um}um ({offset_dbu} DBU)")


# Define the core power domain using the global PG nets found/created earlier
# This domain typically covers the standard cell area (core area)
core_domain = pdngen.setCoreDomain(power=VDD_net, switched_power=switched_power, ground=VSS_net, secondary=secondary)
print(f"Core PDN domain created for nets: Power={VDD_net.getName()}, Ground={VSS_net.getName()}")

# Create the main core grid structure for standard cells and top-level mesh
# A domain can contain multiple grids. This grid covers the main core area.
print("Creating core PDN grid 'core_stdcell_grid'...")
pdngen.makeCoreGrid(domain=core_domain,
    name="core_stdcell_grid",
    starts_with=pdn.GROUND, # Start the stripe pattern with ground (common)
    pin_layers=[], # Layers for power pins to connect to - usually handled by followpin
    generate_obstructions=[], # Define layers to generate routing obstructions over PDN
    powercell=None, # Power cell instance if applicable (not used here)
    powercontrol=None, # Power control instances if applicable (not used here)
    powercontrolnetwork="STAR") # Network type (STAR, RING, etc.)

# Get the created core grid object
core_grid = pdngen.findGrid("core_stdcell_grid")

if core_grid: # Check if grid was created successfully
    # Define PDN parameters from the prompt in microns and convert to DBU
    # Standard Cell / Core Grid parameters
    # power rings on M7 and M8, set width and spacing to 5 and 5 um
    std_cell_ring_width_um = 5.0
    std_cell_ring_spacing_um = 5.0
    # power grids on M1 and M4 for standard cells
    # M1 grid as 0.07 um (used for followpin)
    std_cell_m1_strap_width_um = 0.07
    # M4 grid width is 1.2 um, spacing 1.2 um, pitch 6 um
    std_cell_m4_strap_width_um = 1.2
    std_cell_m4_strap_spacing_um = 1.2
    std_cell_m4_strap_pitch_um = 6.0
    # power grids on M7 and M8
    # width of the power grids on M7 to 1.4 um and set the spacing and the pitch to 1.4 um and 10.8 um.
    # Assume M8 uses the same parameters as M7 grids as per prompt flow
    std_cell_m7_m8_strap_width_um = 1.4
    std_cell_m7_m8_strap_spacing_um = 1.4
    std_cell_m7_m8_strap_pitch_um = 10.8


    std_cell_ring_width = design.micronToDBU(std_cell_ring_width_um)
    std_cell_ring_spacing = design.micronToDBU(std_cell_ring_spacing_um)
    std_cell_m1_strap_width = design.micronToDBU(std_cell_m1_strap_width_um)
    std_cell_m4_strap_width = design.micronToDBU(std_cell_m4_strap_width_um)
    std_cell_m4_strap_spacing = design.micronToDBU(std_cell_m4_strap_spacing_um)
    std_cell_m4_strap_pitch = design.micronToDBU(std_cell_m4_strap_pitch_um)
    std_cell_m7_m8_strap_width = design.micronToDBU(std_cell_m7_m8_strap_width_um)
    std_cell_m7_m8_strap_spacing = design.micronToDBU(std_cell_m7_m8_strap_spacing_um)
    std_cell_m7_m8_strap_pitch = design.micronToDBU(std_cell_m7_m8_strap_pitch_um)

    print(f"Configuring core PDN grid elements:")
    print(f"  Rings (M7/M8): Width={std_cell_ring_width_um}um, Spacing={std_cell_ring_spacing_um}um")
    print(f"  M1 Straps (Followpin): Width={std_cell_m1_strap_width_um}um")
    print(f"  M4 Straps: Width={std_cell_m4_strap_width_um}um, Spacing={std_cell_m4_strap_spacing_um}um, Pitch={std_cell_m4_strap_pitch_um}um")
    print(f"  M7/M8 Straps: Width={std_cell_m7_m8_strap_width_um}um, Spacing={std_cell_m7_m8_strap_spacing_um}um, Pitch={std_cell_m7_m8_strap_pitch_um}um")


    # Add PDN elements to the core grid definition
    # These definitions apply to the entire area covered by the 'core_stdcell_grid' (typically the core area)

    # Create power rings around core area using metal7 and metal8
    # The prompt says "power rings on M7 and M8", which usually implies horizontal on one, vertical on the other.
    # Assuming M7 is horizontal, M8 is vertical based on common 45nm layer directions.
    pdngen.makeRing(grid=core_grid,
        layer0=m7, width0=std_cell_ring_width, spacing0=std_cell_ring_spacing, # Layer 0 for horizontal ring (typically M7)
        layer1=m8, width1=std_cell_ring_width, spacing1=std_cell_ring_spacing, # Layer 1 for vertical ring (typically M8)
        starts_with=pdn.GRID, # Align the ring origin with the grid origin
        offset=offset_dbu, # Offset from the start point (single value for ring)
        pad_offset=pad_offset, # Offset for extending/contracting the ring boundary [L, B, R, T]
        extend=False, # Do not extend beyond the calculated ring boundary
        pad_pin_layers=[], # Layers to connect to if creating rings around pads
        nets=[]) # Empty list means apply to the nets defined by the grid (VDD/VSS)

    # Create horizontal power straps on metal1 following standard cell power rails (Followpin)
    # M1 is typically horizontal in 45nm tech and used for standard cell internal routing
    pdngen.makeFollowpin(grid=core_grid,
        layer=m1,
        width=std_cell_m1_strap_width,
        extend=pdn.CORE) # Extend within the core area boundary

    # Create power straps on metal4
    # M4 is typically vertical in 45nm tech
    pdngen.makeStrap(grid=core_grid,
        layer=m4,
        width=std_cell_m4_strap_width,
        spacing=std_cell_m4_strap_spacing,
        pitch=std_cell_m4_strap_pitch,
        offset=offset_dbu, # Offset from the grid start point
        number_of_straps=0, # Auto calculate number of straps based on pitch and area
        snap=False, # Do not necessarily snap the *first* strap to the grid origin, but follow pitch
        starts_with=pdn.GRID, # Start pattern based on grid origin (e.g., align pitches)
        extend=pdn.CORE, # Extend within the core area (covers std cells and macros)
        nets=[])

    # Create power straps on metal7 (typically horizontal)
    pdngen.makeStrap(grid=core_grid,
        layer=m7,
        width=std_cell_m7_m8_strap_width,
        spacing=std_cell_m7_m8_strap_spacing,
        pitch=std_cell_m7_m8_strap_pitch,
        offset=offset_dbu,
        number_of_straps=0,
        snap=False,
        starts_with=pdn.GRID,
        extend=pdn.RINGS, # Extend to the rings defined on this grid (M7/M8 rings)
        nets=[])

    # Create power straps on metal8 (typically vertical)
    pdngen.makeStrap(grid=core_grid,
        layer=m8,
        width=std_cell_m7_m8_strap_width,
        spacing=std_cell_m7_m8_strap_spacing,
        pitch=std_cell_m7_m8_strap_pitch,
        offset=offset_dbu,
        number_of_straps=0,
        snap=False,
        starts_with=pdn.GRID,
        extend=pdn.BOUNDARY, # Extend to the boundary of the grid (usually aligns with rings or die edge)
        nets=[])

    # Create via connections between core power grid layers
    print("Adding via connections for core PDN grid...")
    # Connect metal1 to metal4
    pdngen.makeConnect(grid=core_grid,
        layer0=m1, layer1=m4,
        cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1]) # 0 pitch uses tech default
    # Connect metal4 to metal7
    pdngen.makeConnect(grid=core_grid,
        layer0=m4, layer1=m7,
        cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])
    # Connect metal7 to metal8
    pdngen.makeConnect(grid=core_grid,
        layer0=m7, layer1=m8,
        cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])

else:
    print("ERROR: Core PDN grid 'core_stdcell_grid' was not created. Cannot add elements.")


# Create power grid for macro blocks if they exist
# if the design has macros, build power grids for macros on M5 and M6 , set the width and spacing of both M5 and M6 grids to 1.2 um, and set the pitch to 6 um.
if len(macros) > 0:
    print("Configuring macro PDN instance grids...")
    # Define PDN parameters for macros in microns and convert to DBU
    macro_strap_width_um = 1.2
    macro_strap_spacing_um = 1.2
    macro_strap_pitch_um = 6.0

    macro_strap_width = design.micronToDBU(macro_strap_width_um)
    macro_strap_spacing = design.micronToDBU(macro_strap_spacing_um)
    macro_strap_pitch = design.micronToDBU(macro_strap_pitch_um)

    print(f"  Macro Grids (M5/M6 Straps): Width={macro_strap_width_um}um, Spacing={macro_strap_spacing_um}um, Pitch={macro_strap_pitch_um}um")

    # Define macro halo for PDN routing (using the same 5um as placement)
    macro_pdn_halo_um = 5.0
    macro_pdn_halo_dbu = design.micronToDBU(macro_pdn_halo_um)
    macro_pdn_halo = [macro_pdn_halo_dbu, macro_pdn_halo_dbu, macro_pdn_halo_dbu, macro_pdn_halo_dbu] # [left, bottom, right, top]
    print(f"  Macro PDN halo: {macro_pdn_halo_um}um ({macro_pdn_halo_dbu} DBU) around each macro")

    # Iterate through each macro instance to create its specific PDN grid
    for i, macro_inst in enumerate(macros):
        inst_name = macro_inst.getName()
        grid_name = f"macro_grid_{inst_name}" # Unique name for each instance grid
        # Use instance name in grid name, potentially truncated or simplified

        print(f"  Creating instance grid '{grid_name}' for macro '{inst_name}'...")
        # Create a separate power grid for each macro instance bounding box plus halo
        pdngen.makeInstanceGrid(domain=core_domain, # Macros typically share the core domain PG nets
            name=grid_name,
            starts_with=pdn.GROUND, # Start pattern with ground
            inst=macro_inst, # Link this grid to a specific instance
            halo=macro_pdn_halo, # Apply a halo around the instance for this grid
            pg_pins_to_boundary=True, # Connect macro PG pins to this grid boundary
            default_grid=False, # This is not the default grid covering the core area
            generate_obstructions=[], # Define routing blockages if needed
            is_bump=False) # Set to True if this grid is for bumps

        # Get the created macro instance grid object
        macro_grid = pdngen.findGrid(grid_name)

        if macro_grid: # Check if grid was created successfully
             print(f"  Adding elements to macro instance PDN grid '{grid_name}'...")
             # Add PDN elements to the macro instance grid definition
             # These definitions apply only within the bounding box of the macro instance + halo

             # Create power straps on metal5 for macro connections (typically horizontal)
             pdngen.makeStrap(grid=macro_grid,
                 layer=m5,
                 width=macro_strap_width,
                 spacing=macro_strap_spacing,
                 pitch=macro_strap_pitch,
                 offset=offset_dbu,
                 number_of_straps=0,
                 snap=True, # Snap the first strap to the grid pattern within the instance box
                 starts_with=pdn.GRID, # Start pattern based on grid origin within the instance box
                 extend=pdn.BOUNDARY, # Extend to the boundary of the instance grid (macro + halo)
                 nets=[])

             # Create power straps on metal6 for macro connections (typically vertical)
             pdngen.makeStrap(grid=macro_grid,
                 layer=m6,
                 width=macro_strap_width,
                 spacing=macro_strap_spacing,
                 pitch=macro_strap_pitch,
                 offset=offset_dbu,
                 number_of_straps=0,
                 snap=True,
                 starts_with=pdn.GRID,
                 extend=pdn.BOUNDARY,
                 nets=[])

             # Create via connections between macro power grid layers and core grid layers
             print(f"  Adding via connections for macro instance PDN grid '{grid_name}'...")
             # Connect metal4 (core grid) to metal5 (macro instance grid)
             pdngen.makeConnect(grid=macro_grid,
                 layer0=m4, layer1=m5,
                 cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1]) # 0 pitch uses tech default
             # Connect metal5 to metal6 (macro instance grid layers)
             pdngen.makeConnect(grid=macro_grid,
                 layer0=m5, layer1=m6,
                 cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])
             # Connect metal6 (macro instance grid) to metal7 (core grid)
             pdngen.makeConnect(grid=macro_grid,
                 layer0=m6, layer1=m7,
                 cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])
        else:
             print(f"  ERROR: Macro instance PDN grid '{grid_name}' was not created for instance '{inst_name}'.")

# Verify the PDN configuration setup before building
print("Checking PDN setup...")
pdngen.checkSetup()
print("PDN setup check complete.")

# Build the power grid shapes and write them to the design database
print("Building and writing PDN grids...")
pdngen.buildGrids(False) # Build the power/ground grid shapes temporarily
pdngen.writeToDb(True) # Write the generated shapes to the database (True means commit changes)
print("PDN grids built and written to DB.")

# Reset temporary shapes created during buildGrids (important!)
pdngen.resetShapes()

# Dump DEF after PDN generation
pdn_def_file = "pdn.def"
print(f"Dumping DEF after PDN generation: {pdn_def_file}")
design.writeDef(pdn_def_file)


# 12. Insert Filler Cells
print("Inserting filler cells...")
# Filler cells fill empty spaces in standard cell rows to maintain uniform density
# and ensure power/ground rails are continuous.
db = ord.get_db()
filler_masters = list()
# Find filler masters in the library (assuming common types like CORE_SPACER)
# Use the specific filler type from the technology LEF, often related to the site name.
# Common types are "CORE_SPACER", "CORE", "SPACER", "FILLER". Check your LEF or documentation.
# For FreePDK45, it might be CORE_SPACER or similar. Let's try a few common ones.
filler_cell_types = ["CORE_SPACER", "CORE", "SPACER", "FILLER"] # Common types to look for

print(f"Searching for filler cells with types: {', '.join(filler_cell_types)}")

for lib in db.getLibs():
    if lib.getTech() == tech_db: # Only check libraries for the current technology
        for master in lib.getMasters():
            if master.getType().getName() in filler_cell_types:
                 filler_masters.append(master)
                 # print(f"  Found filler master: {master.getName()} (Type: {master.getType().getName()})")
            # Optional: Also search by name pattern if type isn't sufficient
            # elif "FILL" in master.getName().upper() or "SPACER" in master.getName().upper():
            #     print(f"  Found potential filler master by name: {master.getName()} (Type: {master.getType().getName()})")
            #     # Decide if you want to include these based on confidence
            #     # filler_masters.append(master)


if not filler_masters:
    print("WARNING: No filler cells found in library with specified types.")
    print("Filler insertion may fail or be skipped.")
    # Skipping filler placement if no masters are found
else:
    # Perform filler placement using the detailed placer
    print(f"Performing filler placement using {len(filler_masters)} master(s)...")
    # The prefix is used for the generated filler instance names
    opendp.fillerPlacement(
        filler_masters=filler_masters,
        prefix="FILLER_", # A common prefix for filler instances
        verbose=False # Set to True for debug messages from the tool
    )
    print("Filler placement complete.")

    # Dump DEF after filler insertion
    filler_def_file = "filler.def"
    print(f"Dumping DEF after filler insertion: {filler_def_file}")
    design.writeDef(filler_def_file)


# 13. Global Routing
print("Performing global routing...")
# Get the global router object (GlobalRouter tool)
grt = design.getGlobalRouter()

# Set routing layer ranges for signal and clock nets
# Routing up to metal7 as requested
signal_low_layer_name = "metal1"
signal_high_layer_name = "metal7"
# Use tech_db to get layer objects and their routing levels
signal_low_layer_obj = tech_db.findLayer(signal_low_layer_name)
signal_high_layer_obj = tech_db.findLayer(signal_high_layer_name)

if not signal_low_layer_obj or not signal_high_layer_obj:
     print(f"ERROR: Global routing layers '{signal_low_layer_name}' or '{signal_high_layer_name}' not found.")
     ord.finish()
     sys.exit(1)

signal_low_layer_level = signal_low_layer_obj.getRoutingLevel()
signal_high_layer_level = signal_high_layer_obj.getRoutingLevel()

print(f"Setting global routing layer range: {signal_low_layer_name} (level {signal_low_layer_level}) to {signal_high_layer_name} (level {signal_high_layer_level})")
grt.setMinRoutingLayer(signal_low_layer_level)
grt.setMaxRoutingLayer(signal_high_layer_level)

# Use the same range for clock nets as requested for signal nets
# The prompt says "routing up to metal7", implying signal nets.
# CTS handles clock routing, but global router may guide it or route non-tree clock signals.
# Setting the clock routing layers here ensures consistency if GR handles clock nets.
clk_low_layer_level = signal_low_layer_level
clk_high_layer_level = signal_high_layer_level
print(f"Setting global routing clock layer range: {signal_low_layer_name} (level {clk_low_layer_level}) to {signal_high_layer_name} (level {clk_high_layer_level})")
grt.setMinLayerForClock(clk_low_layer_level)
grt.setMaxLayerForClock(clk_high_layer_level)


# Set global routing adjustment factor (influences congestion reduction)
# A value like 0.5 means capacity is reduced by 50% (more conservative)
grt_adjustment = 0.5
print(f"Setting global routing adjustment: {grt_adjustment}")
grt.setAdjustment(grt_adjustment)

# Enable verbose output from the global router
grt.setVerbose(True)

# Run global routing algorithm
print("Running global router...")
# The boolean argument (True) typically means to commit the resulting guides to the database.
grt.globalRoute(True)
print("Global routing complete.")

# Dump DEF after global routing
global_route_def_file = "global_route.def"
print(f"Dumping DEF after global routing: {global_route_def_file}")
design.writeDef(global_route_def_file)


# 14. Detailed Routing
print("Performing detailed routing...")
# Get the detailed router object (TritonRoute tool)
drter = design.getTritonRoute()
params = drt.ParamStruct() # Detailed routing parameters structure

# Configure basic detailed routing parameters
params.outputMazeFile = "" # Optional: output maze files for visualization/debug
params.outputDrcFile = "" # Optional: output DRC violations file
params.outputCmapFile = "" # Optional: output congestion map file
params.outputGuideCoverageFile = "" # Optional: output guide coverage report
params.dbProcessNode = "" # Optional: Specify process node if needed by techfile

params.enableViaGen = True # Enable automatic via generation during routing
params.drouteEndIter = 1 # Number of detailed routing iterations (start with 1, increase if needed for DRC closure)
print(f"Setting detailed routing iterations: {params.drouteEndIter}")

# Specify routing layer range for the detailed router using layer names
params.bottomRoutingLayer = signal_low_layer_name
params.topRoutingLayer = signal_high_layer_name
print(f"Setting detailed routing layer range: {params.bottomRoutingLayer} to {params.topRoutingLayer}")

params.verbose = 1 # Verbosity level (0: quiet, 1: normal, 2: verbose)
params.cleanPatches = True # Clean up routing patches after routing
params.doPa = True # Perform post-route antenna fixing (recommended)

# Set detailed placement object if needed by router (usually not needed if DP is done before GR)
# params.detailedPlacement = opendp

# Set the configured parameters in the detailed router object
drter.setParams(params)

# Run detailed routing algorithm
print("Running detailed router...")
drter.main() # Execute detailed routing
print("Detailed routing complete.")

# Dump DEF after detailed routing (this is typically the final DEF for manufacturing)
detailed_route_def_file = "detailed_route.def"
print(f"Dumping DEF after detailed routing: {detailed_route_def_file}")
design.writeDef(detailed_route_def_file)


# 15. Save Final ODB database
final_odb_file = "final.odb"
print(f"Saving final ODB database: {final_odb_file}")
design.writeDb(final_odb_file)

# 16. Finalize OpenROAD
print("Finalizing OpenROAD.")
ord.finish()

# Close the log file if it was opened
# if 'log_file' in locals() and log_file and not log_file.closed:
#    log_file.close()

print("Script finished successfully.")