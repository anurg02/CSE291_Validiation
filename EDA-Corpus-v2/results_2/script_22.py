# -----------------------------------------------------------------------------
# OpenROAD Script - Consolidated Flow
# -----------------------------------------------------------------------------
# This script consolidates steps for a basic OpenROAD design flow,
# including reading inputs, floorplanning, placement, PDN generation,
# CTS, and routing, based on user-provided requirements.
#
# Input: Gate-level Verilog netlist (design_top_module_name.v), tech LEF,
#        library LEFs, and liberty files.
# Output: DEF files at each stage, final Verilog netlist, final OpenDB.
#
# Requirements from prompt:
# - Clock port "clk", period 50 ns.
# - Floorplan: Die (0,0)-(45,45), Core (5,5)-(40,40) um.
# - Macro Placement: Fence (5,5)-(20,25) um, Halo 5 um, min spacing 5 um.
# - Placement: Macro placement, Global placement (approx 20 iterations),
#              Detailed placement (max disp 1um X, 3um Y).
# - CTS: Buffer BUF_X2, wire RC (0.03574, 0.07516).
# - PDN:
#   - Core Rings: M7, M8, width 4um, spacing 4um.
#   - Core Grids: M1 (followpin, width 0.07um), M4 (strap, w=1.2, s=1.2, p=6),
#                 M7 (strap, w=1.4, s=1.4, p=10.8), M8 (strap, w=1.4, s=1.4, p=10.8).
#   - Macro PDN (if macros exist): Rings M5, M6 (w=1.5, s=1.5), Grids M5, M6 (w=1.2, s=1.2, p=6).
#   - Vias: Zero offset (interpreted as default grid alignment), Zero pitch (interpretation removed due to ambiguity).
#   - Offset: 0 for rings/straps from boundaries.
# - Routing: Global (M1-M7), Detailed (M1-M7).
# - Output: DEF at each stage, final Verilog/ODB.

import openroad as ord
import odb
import pdn
import drt
from pathlib import Path

# --- Configuration Paths ---
# Set paths to library and design files relative to script location
# *** User needs to modify these paths for their specific environment ***
script_dir = Path(__file__).parent
baseDir = script_dir.parent # Assuming script is in a subdir like 'scripts'
libDir = baseDir / "Design" / "nangate45" / "lib"
lefDir = baseDir / "Design" / "nangate45" / "lef"
designDir = baseDir / "Design"

design_top_module_name = "gcd" # Set your top module name
verilog_file = designDir / "1_synth.v" # Set your input Verilog netlist

# --- Initialization ---
print("--- Initializing OpenROAD ---")
# Initialize OpenROAD database and tools
tech = ord.Tech()
design = ord.Design(tech)

# Read technology, LEF, and liberty files
print(f"Reading liberty files from {libDir}")
libFiles = sorted(libDir.glob("*.lib"))
for libFile in libFiles:
    tech.readLiberty(libFile.as_posix())

print(f"Reading LEF files from {lefDir}")
techLefFiles = sorted(lefDir.glob("*.tech.lef"))
for techLefFile in techLefFiles:
    tech.readLef(techLefFile.as_posix())

lefFiles = sorted(lefDir.glob('*.lef'))
for lefFile in lefFiles:
    tech.readLef(lefFile.as_posix())

# Create design block and read Verilog netlist
print(f"Reading Verilog netlist: {verilog_file}")
design.readVerilog(verilog_file.as_posix())
print(f"Linking design with top module: {design_top_module_name}")
design.link(design_top_module_name)

# Write initial DEF
initial_def_path = "initial.def"
print(f"Writing initial DEF: {initial_def_path}")
design.writeDef(initial_def_path)

# --- Set Clock ---
print("\n--- Setting Clock ---")
clock_period_ns = 50.0
clock_port_name = "clk"
clock_name = "core_clock"

print(f"Creating clock '{clock_name}' on port '{clock_port_name}' with period {clock_period_ns} ns")
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
# Propagate clock needed for timing analysis in later stages
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# --- Floorplan ---
print("\n--- Performing Floorplan ---")
floorplan = design.getFloorplan()

# Set die area to 45um x 45um starting at (0,0)
die_lx = 0.0
die_ly = 0.0
die_ux = 45.0
die_uy = 45.0
die_area_dbu = odb.Rect(design.micronToDBU(die_lx), design.micronToDBU(die_ly),
                        design.micronToDBU(die_ux), design.micronToDBU(die_uy))

# Set core area to 35um x 35um starting at (5,5)
core_lx = 5.0
core_ly = 5.0
core_ux = 40.0
core_uy = 40.0
core_area_dbu = odb.Rect(design.micronToDBU(core_lx), design.micronToDBU(core_ly),
                         design.micronToDBU(core_ux), design.micronToDBU(core_uy))

# Find the standard cell site from the loaded library
# *** Adjust site name if needed for your technology library ***
site_name = "FreePDK45_38x28_10R_NP_162NW_34O" # Example site name
site = floorplan.findSite(site_name)
if site is None:
    print(f"Error: Standard cell site '{site_name}' not found. Please check library files and site name.")
    exit()
print(f"Using standard cell site: {site_name}")

# Initialize the floorplan with the calculated areas and the site
print(f"Initializing floorplan: Die area {die_lx},{die_ly}-{die_ux},{die_uy} um, Core area {core_lx},{core_ly}-{core_ux},{core_uy} um")
floorplan.initFloorplan(die_area_dbu, core_area_dbu, site)

# Create placement tracks within the core area
print("Creating placement tracks")
floorplan.makeTracks()

# Write DEF after floorplanning
floorplan_def_path = "floorplan.def"
print(f"Writing DEF after floorplanning: {floorplan_def_path}")
design.writeDef(floorplan_def_path)

# --- Macro Placement ---
print("\n--- Performing Macro Placement ---")
# Identify macro instances (instances with a master that is a 'block' type)
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    print(f"Found {len(macros)} macro instances.")
    mpl = design.getMacroPlacer()
    
    # Set the fence region for macros in microns
    fence_lx = 5.0
    fence_ly = 5.0
    fence_ux = 20.0
    fence_uy = 25.0
    print(f"Setting macro fence region: {fence_lx},{fence_ly}-{fence_ux},{fence_uy} um")
    mpl.setFenceRegion(fence_lx, fence_ly, fence_ux, fence_uy)
    
    # Set the minimum spacing between macro boundaries (5 um)
    min_macro_space = 5.0
    print(f"Setting minimum macro spacing: {min_macro_space} um")
    design.evalTclString(f"set_macro_space -distance {min_macro_space}")

    # Configure and run macro placement
    print("Running macro placement...")
    mpl.place(
        num_threads = 4,
        halo_width = 5.0,  # Set halo region width around each macro (in microns)
        halo_height = 5.0, # Set halo region height around each macro (in microns)
        fence_lx = fence_lx,
        fence_ly = fence_ly,
        fence_ux = fence_ux,
        fence_uy = fence_uy,
        snap_layer = 4,    # Align macro pins on metal4 with the track grid (example)
        # Other parameters use defaults from the C++ implementation if not specified
        # The parameters below are included for clarity and match the Gemini draft defaults where applicable.
        max_num_macro = 0,
        min_num_macro = 0,
        max_num_inst = 0,
        min_num_inst = 0,
        tolerance = 0.1,
        max_num_level = 2,
        coarsening_ratio = 10.0,
        large_net_threshold = 50,
        signature_net_threshold = 50,
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
        bus_planning_flag = False,
        report_directory = ""
    )
else:
    print("No macro instances found. Skipping macro placement step.")

# Write DEF after macro placement
macro_place_def_path = "macro_place.def"
print(f"Writing DEF after macro placement: {macro_place_def_path}")
design.writeDef(macro_place_def_path)

# --- Global Placement ---
print("\n--- Performing Global Placement ---")
gpl = design.getReplace()

# Set modes for placement
print("Configuring global placement parameters...")
gpl.setTimingDrivenMode(False) # Timing-driven placement off for this example
gpl.setRoutabilityDrivenMode(True) # Enable routability-driven placement
gpl.setUniformTargetDensityMode(True) # Enable uniform target density

# Set initial placement iterations (requested 20 times, likely refers to placer iterations)
# Note: This sets the max iterations for the initial phase, not global routing.
initial_place_max_iter = 20
print(f"Setting initial placement max iterations: {initial_place_max_iter}")
gpl.setInitialPlaceMaxIter(initial_place_max_iter)
gpl.setInitDensityPenalityFactor(0.05) # Example initial density penalty

# Perform initial placement
print("Running initial placement...")
gpl.doInitialPlace(threads = 4)

# Perform Nesterov placement (quadratic placement refinement)
print("Running Nesterov placement...")
gpl.doNesterovPlace(threads = 4)

# Reset the placer state - good practice after completing a placement stage
gpl.reset()

# Write DEF after global placement
global_place_def_path = "global_place.def"
print(f"Writing DEF after global placement: {global_place_def_path}")
design.writeDef(global_place_def_path)

# --- Detailed Placement ---
print("\n--- Performing Detailed Placement ---")
dp = design.getOpendp()

# Set maximum displacement allowed for detailed placement (requested 1um X, 3um Y)
max_disp_x_um = 1.0
max_disp_y_um = 3.0
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)
print(f"Setting detailed placement max displacement: {max_disp_x_um} um X, {max_disp_y_um} um Y")

# Remove filler cells if they were inserted before detailed placement (unlikely in this flow, but safe)
dp.removeFillers()

# Perform detailed placement
print("Running detailed placement...")
dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False) # Parameters: max_disp_x, max_disp_y, skip_inst, verbose

# Write DEF after detailed placement
detailed_place_def_path = "detailed_place.def"
print(f"Writing DEF after detailed placement: {detailed_place_def_path}")
design.writeDef(detailed_place_def_path)

# --- Power Delivery Network (PDN) ---
print("\n--- Generating Power Delivery Network (PDN) ---")
pdngen = design.getPdnGen()
block = design.getBlock()
tech_db = design.getTech().getDB().getTech()

# Get metal layers required for PDN construction
m1 = tech_db.findLayer("metal1")
m4 = tech_db.findLayer("metal4")
m5 = tech_db.findLayer("metal5")
m6 = tech_db.findLayer("metal6")
m7 = tech_db.findLayer("metal7")
m8 = tech_db.findLayer("metal8")

# Check if required layers are found
required_layers = { "metal1": m1, "metal4": m4, "metal5": m5,
                    "metal6": m6, "metal7": m7, "metal8": m8 }
for layer_name, layer_obj in required_layers.items():
    if layer_obj is None:
        print(f"Error: Required layer '{layer_name}' not found in technology LEF.")
        exit()
print("Required metal layers found.")

# Find or create power/ground nets and mark as special
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

if VDD_net is None:
    print("VDD net not found, creating...")
    VDD_net = odb.dbNet_create(block, "VDD")
if VSS_net is None:
    print("VSS net not found, creating...")
    VSS_net = odb.dbNet_create(block, "VSS")

# Mark nets as special for PDN tool
VDD_net.setSpecial()
VDD_net.setSigType("POWER")
VSS_net.setSpecial()
VSS_net.setSigType("GROUND")
print("VDD and VSS nets set up.")

# Connect standard cell power/ground pins to the global nets
print("Connecting VDD/VSS pins globally...")
# This command finds all pins matching pinPattern on instances matching instPattern
# and connects them to the specified net.
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VDD$", net=VDD_net, do_connect=True)
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VSS$", net=VSS_net, do_connect=True)
block.globalConnect() # Apply the global connections

# Configure core power domain
core_domain = pdngen.setCoreDomain(power=VDD_net, ground=VSS_net)
domains = [core_domain]
print("Core power domain configured.")

# Halo around macros for PDN routing (using the same value as macro placement halo)
macro_pdn_halo_um = 5.0
macro_pdn_halo_dbu = [design.micronToDBU(macro_pdn_halo_um) for i in range(4)]
print(f"Setting macro PDN halo: {macro_pdn_halo_um} um")

# --- Create Power Grid for Standard Cells (Core Grid) ---
print("Creating core PDN grid...")
for domain in domains:
    # Create the main core grid structure definition
    pdngen.makeCoreGrid(domain = domain,
        name = "core_pdn_grid",
        starts_with = pdn.GROUND, # Pattern starts with ground net (VSS)
        # Other parameters use defaults
        )

# Find the created core grid definition
core_grid_defs = pdngen.findGrid("core_pdn_grid")

# Add rings and straps to the core grid definitions
for g in core_grid_defs:
    # Create power rings around core area using metal7 and metal8
    # Ring width and spacing = 4 um
    core_ring_width_um = 4.0
    core_ring_spacing_um = 4.0
    core_ring_width_dbu = design.micronToDBU(core_ring_width_um)
    core_ring_spacing_dbu = design.micronToDBU(core_ring_spacing_um)
    # Offset from core boundary = 0 um (requested)
    core_ring_core_offset_dbu = [design.micronToDBU(0.0) for i in range(4)]

    print(f"Adding core rings on {m7.getName()}/{m8.getName()} w={core_ring_width_um} s={core_ring_spacing_um} um, offset=0 um")
    pdngen.makeRing(grid = g,
        layer0 = m7,
        width0 = core_ring_width_dbu,
        spacing0 = core_ring_spacing_dbu,
        layer1 = m8,
        width1 = core_ring_width_dbu,
        spacing1 = core_ring_spacing_dbu,
        starts_with = pdn.GRID, # Ring pattern starts aligned with grid origin
        offset = core_ring_core_offset_dbu,
        pad_offset = [0, 0, 0, 0], # No connection to pads
        extend = False, # Do not extend the ring
        pad_pin_layers = [], # No connection layers to pads
        nets = []) # Apply to all nets in the domain (VDD/VSS)

    # Create horizontal power straps on metal1 following cell power rails
    # Width = 0.07 um
    m1_strap_width_um = 0.07
    m1_strap_width_dbu = design.micronToDBU(m1_strap_width_um)
    print(f"Adding M1 followpin straps w={m1_strap_width_um} um")
    pdngen.makeFollowpin(grid = g,
        layer = m1,
        width = m1_strap_width_dbu,
        extend = pdn.CORE) # Extend straps to the core boundary

    # Create power straps on metal4
    # Width = 1.2 um, Spacing = 1.2 um, Pitch = 6 um
    m4_strap_width_um = 1.2
    m4_strap_spacing_um = 1.2
    m4_strap_pitch_um = 6.0
    m4_strap_offset_um = 0.0 # Requested offset 0
    m4_strap_width_dbu = design.micronToDBU(m4_strap_width_um)
    m4_strap_spacing_dbu = design.micronToDBU(m4_strap_spacing_um)
    m4_strap_pitch_dbu = design.micronToDBU(m4_strap_pitch_um)
    m4_strap_offset_dbu = design.micronToDBU(m4_strap_offset_um)

    print(f"Adding M4 straps w={m4_strap_width_um} s={m4_strap_spacing_um} p={m4_strap_pitch_um} um, offset=0 um")
    pdngen.makeStrap(grid = g,
        layer = m4,
        width = m4_strap_width_dbu,
        spacing = m4_strap_spacing_dbu,
        pitch = m4_strap_pitch_dbu,
        offset = m4_strap_offset_dbu,
        number_of_straps = 0,  # Auto-calculate number of straps
        snap = False, # Pitch defines placement, not snapping to a different grid
        starts_with = pdn.GRID, # Strap pattern starts aligned with grid origin
        extend = pdn.CORE, # Extend straps to core boundary
        nets = []) # Apply to all nets in the domain (VDD/VSS)

    # Create power straps on metal7 and metal8
    # Width = 1.4 um, Spacing = 1.4 um, Pitch = 10.8 um
    m7_m8_strap_width_um = 1.4
    m7_m8_strap_spacing_um = 1.4
    m7_m8_strap_pitch_um = 10.8
    m7_m8_strap_offset_um = 0.0 # Requested offset 0
    m7_m8_strap_width_dbu = design.micronToDBU(m7_m8_strap_width_um)
    m7_m8_strap_spacing_dbu = design.micronToDBU(m7_m8_strap_spacing_um)
    m7_m8_strap_pitch_dbu = design.micronToDBU(m7_m8_strap_pitch_um)
    m7_m8_strap_offset_dbu = design.micronToDBU(m7_m8_strap_offset_um)

    print(f"Adding M7/M8 straps w={m7_m8_strap_width_um} s={m7_m8_strap_spacing_um} p={m7_m8_strap_pitch_um} um, offset=0 um")
    pdngen.makeStrap(grid = g,
        layer = m7,
        width = m7_m8_strap_width_dbu,
        spacing = m7_m8_strap_spacing_dbu,
        pitch = m7_m8_strap_pitch_dbu,
        offset = m7_m8_strap_offset_dbu,
        number_of_straps = 0,
        snap = False,
        starts_with = pdn.GRID,
        extend = pdn.CORE, # Extend straps to core boundary
        nets = [])

    pdngen.makeStrap(grid = g,
        layer = m8,
        width = m7_m8_strap_width_dbu,
        spacing = m7_m8_strap_spacing_dbu,
        pitch = m7_m8_strap_pitch_dbu,
        offset = m7_m8_strap_offset_dbu,
        number_of_straps = 0,
        snap = False,
        starts_with = pdn.GRID,
        extend = pdn.CORE, # Extend straps to core boundary
        nets = [])

    # Create via connections between core grid layers
    # Note: Removed explicit cut_pitch_x/y=0 as it's not standard and ambiguous.
    # Default via placement connects overlapping straps/rings at intersections.
    print("Adding via connections for core grid...")
    pdngen.makeConnect(grid = g, layer0 = m1, layer1 = m4) # Connect M1 followpin to M4 straps
    pdngen.makeConnect(grid = g, layer0 = m4, layer1 = m7) # Connect M4 straps to M7 straps/rings
    pdngen.makeConnect(grid = g, layer0 = m7, layer1 = m8) # Connect M7 to M8 straps/rings

# --- Create Power Grid for Macro Blocks (if any) ---
if len(macros) > 0:
    print("Creating macro PDN grids...")
    # Set PG ring config for macros
    macro_ring_width_um = 1.5
    macro_ring_spacing_um = 1.5
    macro_ring_width_dbu = design.micronToDBU(macro_ring_width_um)
    macro_ring_spacing_dbu = design.micronToDBU(macro_ring_spacing_um)
    # Offset from macro boundary = 0 um (requested)
    macro_ring_macro_offset_dbu = [design.micronToDBU(0.0) for i in range(4)]

    # Set macro strap config
    macro_strap_width_um = 1.2
    macro_strap_spacing_um = 1.2
    macro_strap_pitch_um = 6.0
    macro_strap_offset_um = 0.0 # Requested offset 0
    macro_strap_width_dbu = design.micronToDBU(macro_strap_width_um)
    macro_strap_spacing_dbu = design.micronToDBU(macro_strap_spacing_um)
    macro_strap_pitch_dbu = design.micronToDBU(macro_strap_pitch_um)
    macro_strap_offset_dbu = design.micronToDBU(macro_strap_offset_um)

    for i, macro_inst in enumerate(macros):
        # Create separate power grid definition for each macro instance
        for domain in domains:
            pdngen.makeInstanceGrid(domain = domain,
                name = f"macro_pdn_grid_{macro_inst.getName()}",
                starts_with = pdn.GROUND, # Start with ground
                inst = macro_inst,
                halo = macro_pdn_halo_dbu, # Use the defined halo around macros
                pg_pins_to_boundary = True,  # Connect power/ground pins to boundary
                default_grid = False, # This is a macro-specific grid
                # Other parameters use defaults
                )

        # Find the created macro grid definition
        macro_grid_defs = pdngen.findGrid(f"macro_pdn_grid_{macro_inst.getName()}")

        # Add rings and straps to the macro grid definitions
        for g in macro_grid_defs:
            # Create power ring around macro using metal5 and metal6
            # Width and spacing = 1.5 um, offset = 0 um
            print(f"Adding rings around macro '{macro_inst.getName()}' on {m5.getName()}/{m6.getName()} w={macro_ring_width_um} s={macro_ring_spacing_um} um, offset=0 um")
            pdngen.makeRing(grid = g,
                layer0 = m5,
                width0 = macro_ring_width_dbu,
                spacing0 = macro_ring_spacing_dbu,
                layer1 = m6,
                width1 = macro_ring_width_dbu,
                spacing1 = macro_ring_spacing_dbu,
                starts_with = pdn.GRID, # Ring starts aligned with grid origin
                offset = macro_ring_macro_offset_dbu, # Offset from macro boundary
                pad_offset = [0, 0, 0, 0], # No connection to pads
                extend = False, # Do not extend ring
                pad_pin_layers = [], # No connection layers to pads
                nets = []) # Apply to all nets in the domain

            # Create power straps on metal5 and metal6 for macro connections
            # Width = 1.2 um, Spacing = 1.2 um, Pitch = 6 um, offset = 0 um
            print(f"Adding straps for macro '{macro_inst.getName()}' on {m5.getName()}/{m6.getName()} w={macro_strap_width_um} s={macro_strap_spacing_um} p={macro_strap_pitch_um} um, offset=0 um")
            pdngen.makeStrap(grid = g,
                layer = m5,
                width = macro_strap_width_dbu,
                spacing = macro_strap_spacing_dbu,
                pitch = macro_strap_pitch_dbu,
                offset = macro_strap_offset_dbu,
                number_of_straps = 0, # Auto-calculate
                snap = True, # Snap straps to the pitch grid
                starts_with = pdn.GRID, # Strap pattern starts aligned with grid origin
                extend = pdn.RINGS, # Extend straps to the macro rings
                nets = []) # Apply to all nets in the domain

            pdngen.makeStrap(grid = g,
                layer = m6,
                width = macro_strap_width_dbu,
                spacing = macro_strap_spacing_dbu,
                pitch = macro_strap_pitch_dbu,
                offset = macro_strap_offset_dbu,
                number_of_straps = 0,
                snap = True,
                starts_with = pdn.GRID,
                extend = pdn.RINGS, # Extend straps to the macro rings
                nets = []) # Apply to all nets in the domain

            # Create via connections between macro power grid layers and core grid layers
            # Note: Removed explicit cut_pitch_x/y=0
            print(f"Adding via connections for macro grid '{macro_inst.getName()}'...")
            # Connect metal4 (from core grid) to metal5 (macro grid)
            pdngen.makeConnect(grid = g, layer0 = m4, layer1 = m5)
            # Connect metal5 to metal6 (macro grid layers)
            pdngen.makeConnect(grid = g, layer0 = m5, layer1 = m6)
            # Connect metal6 (macro grid) to metal7 (core grid)
            pdngen.makeConnect(grid = g, layer0 = m6, layer1 = m7)

# Verify PDN setup
print("Checking PDN setup...")
pdngen.checkSetup()

# Build the power grid structures
print("Building PDN grids...")
pdngen.buildGrids(False) # False means do not trim shapes

# Write the generated PDN shapes to the design database
print("Writing PDN shapes to database...")
pdngen.writeToDb(True, ) # True means add pins

# Reset temporary shapes used during PDN generation
pdngen.resetShapes()

# Write DEF after PDN generation
pdn_def_path = "pdn.def"
print(f"Writing DEF after PDN generation: {pdn_def_path}")
design.writeDef(pdn_def_path)

# --- Clock Tree Synthesis (CTS) ---
print("\n--- Performing Clock Tree Synthesis (CTS) ---")
cts = design.getTritonCts()

# Set propagated clock for timing analysis before CTS
# This was already done after create_clock, but good practice to ensure
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Set unit resistance and capacitance for clock and signal nets
rc_resistance = 0.03574
rc_capacitance = 0.07516
print(f"Setting wire RC: R={rc_resistance}, C={rc_capacitance}")
design.evalTclString(f"set_wire_rc -clock -resistance {rc_resistance} -capacitance {rc_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {rc_resistance} -capacitance {rc_capacitance}")

# Set the clock buffer cell to use (BUF_X2 requested)
buffer_cell_name = "BUF_X2" # *** Adjust buffer cell name if needed ***
print(f"Setting CTS buffer cell: {buffer_cell_name}")
cts.setBufferList(buffer_cell_name) # List of buffers CTS can use
cts.setRootBuffer(buffer_cell_name) # Buffer to use at the clock root
cts.setSinkBuffer(buffer_cell_name) # Buffer to use for balancing/sinks

# Run CTS
print("Running TritonCTS...")
cts.runTritonCts()

# Write DEF after CTS
cts_def_path = "cts.def"
print(f"Writing DEF after CTS: {cts_def_path}")
design.writeDef(cts_def_path)

# --- Filler Cell Placement ---
print("\n--- Inserting Filler Cells ---")
db = ord.get_db()
filler_masters = list()
# Find filler cell masters in the library (adjust prefix/type if needed)
filler_cells_prefix = "FILLCELL_" # Example prefix
print(f"Searching for filler cells with type CORE_SPACER and/or prefix '{filler_cells_prefix}'")
for lib in db.getLibs():
    for master in lib.getMasters():
        # Check if the cell is a CORE_SPACER type (standard filler type)
        # Also check by prefix as a fallback
        if master.getType() == "CORE_SPACER" or master.getName().startswith(filler_cells_prefix):
            filler_masters.append(master)

if len(filler_masters) == 0:
    print("Warning: No CORE_SPACER or prefix-matching filler cells found in library. Skipping filler placement.")
else:
    print(f"Found {len(filler_masters)} filler cell masters.")
    # Perform filler placement using OpenDP
    print("Running filler placement...")
    dp.fillerPlacement(filler_masters = filler_masters,
                       prefix = filler_cells_prefix, # Optional prefix for created instances
                       verbose = False) # Set to True for detailed output

# Write DEF after filler placement
filler_def_path = "filler.def"
print(f"Writing DEF after filler placement: {filler_def_path}")
design.writeDef(filler_def_path)

# --- Global Routing ---
print("\n--- Performing Global Routing ---")
grt = design.getGlobalRouter()
tech = design.getTech().getDB().getTech()

# Set routing layer ranges for signal and clock nets (metal1 to metal7 requested)
# Find the routing levels for the specified layers
metal1_layer = tech.findLayer("metal1")
metal7_layer = tech.findLayer("metal7")

if metal1_layer is None or metal7_layer is None:
    print("Error: Metal1 or Metal7 layer not found for global routing.")
    exit()

signal_low_layer_level = metal1_layer.getRoutingLevel()
signal_high_layer_level = metal7_layer.getRoutingLevel()
clk_low_layer_level = metal1_layer.getRoutingLevel()
clk_high_layer_level = metal7_layer.getRoutingLevel() # Use the same range for clock

print(f"Setting signal routing layers: {metal1_layer.getName()} (level {signal_low_layer_level}) to {metal7_layer.getName()} (level {signal_high_layer_level})")
grt.setMinRoutingLayer(signal_low_layer_level)
grt.setMaxRoutingLayer(signal_high_layer_level)

print(f"Setting clock routing layers: {metal1_layer.getName()} (level {clk_low_layer_level}) to {metal7_layer.getName()} (level {clk_high_layer_level})")
grt.setMinLayerForClock(clk_low_layer_level)
grt.setMaxLayerForClock(clk_high_layer_level)

# Set routing adjustment (example value to control congestion)
# A higher value reserves more track space.
grt_adjustment = 0.5
print(f"Setting global router adjustment: {grt_adjustment}")
grt.setAdjustment(grt_adjustment)
grt.setVerbose(True) # Enable verbose output

# Run global routing
# The requested "20 iterations" is ambiguous for global routing;
# `globalRoute(True)` enables congestion-driven routing which is iterative internally.
print("Running global routing...")
grt.globalRoute(True) # True enables congestion-driven routing

# Write DEF after global routing
global_route_def_path = "global_route.def"
print(f"Writing DEF after global routing: {global_route_def_path}")
design.writeDef(global_route_def_path)

# --- Detailed Routing ---
print("\n--- Performing Detailed Routing ---")
drter = design.getTritonRoute()
params = drt.ParamStruct()

# Configure detailed routing parameters
print("Configuring detailed routing parameters...")
# Set the layer range for detailed routing
params.bottomRoutingLayer = metal1_layer.getName()
params.topRoutingLayer = metal7_layer.getName()
print(f"Setting detailed routing layers: {params.bottomRoutingLayer} to {params.topRoutingLayer}")

params.enableViaGen = True # Enable via generation
params.drouteEndIter = 1 # Run 1 detailed routing iteration (usually sufficient after good global route)
params.doPa = True # Perform pin access optimization
params.minAccessPoints = 1 # Minimum pin access points per pin

# Optional: Set output files for debugging (commented out by default)
# params.outputMazeFile = "maze.rou"
# params.outputDrcFile = "drc.rpt"
# params.outputCmapFile = "cmap.out"
# params.outputGuideCoverageFile = "guide_coverage.rpt"

# Other parameters using defaults or typical values
params.dbProcessNode = ""
params.viaInPinBottomLayer = ""
params.viaInPinTopLayer = ""
params.orSeed = -1
params.orK = 0
params.verbose = 1
params.cleanPatches = True
params.singleStepDR = False
params.saveGuideUpdates = False
params.fixAntenna = True # Enable antenna fixing

# Set the configured parameters
drter.setParams(params)

# Run detailed routing
print("Running TritonRoute...")
drter.main()

# Write DEF after detailed routing
detailed_route_def_path = "detailed_route.def"
print(f"Writing DEF after detailed routing: {detailed_route_def_path}")
design.writeDef(detailed_route_def_path)

# --- Save Final Outputs ---
print("\n--- Saving Final Outputs ---")
# Write final Verilog netlist (with placed/routed instances)
final_verilog_path = "final.v"
print(f"Writing final Verilog: {final_verilog_path}")
# The write_verilog command needs the output file path
design.evalTclString(f"write_verilog {final_verilog_path}")


# Write final OpenDB file
final_odb_path = "final.odb"
print(f"Writing final OpenDB: {final_odb_path}")
design.writeDb(final_odb_path)

print("\n--- OpenROAD Flow Completed ---")