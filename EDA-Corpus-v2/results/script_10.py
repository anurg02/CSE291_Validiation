import openroad as ord
from openroad import Tech, Design, Timing
from pathlib import Path
import odb
import pdn
import psm
import drt

# --- Setup Paths and Design ---
# Define paths to library and design files (replace with your actual paths)
libDir = Path("lib")
lefDir = Path("lef")
designDir = Path(".")

# Define design parameters
verilog_file = designDir / "design.v" # Replace with your Verilog netlist file
design_top_module_name = "top" # Replace with your top module name
tech_lef_pattern = "*.tech.lef" # Pattern for technology LEF files
cell_lef_pattern = "*.lef" # Pattern for cell LEF files
lib_pattern = "*.lib" # Pattern for liberty files

# Initialize OpenROAD objects and read technology files
tech = Tech()

# Read all liberty (.lib) and LEF files from the library directories
print(f"Reading liberty files from {libDir}")
for libFile in libDir.glob(lib_pattern):
    tech.readLiberty(libFile.as_posix())

print(f"Reading LEF files from {lefDir}")
techLefFiles = lefDir.glob(tech_lef_pattern)
lefFiles = lefDir.glob(cell_lef_pattern)

# Load technology and cell LEF files
for techLefFile in techLefFiles:
    tech.readLef(techLefFile.as_posix())
for lefFile in lefFiles:
    tech.readLef(lefFile.as_posix())

# Create design and read Verilog netlist
design = Design(tech)
print(f"Reading Verilog file {verilog_file}")
design.readVerilog(verilog_file.as_posix())

# Link the design to resolve hierarchical references
print(f"Linking design top module: {design_top_module_name}")
design.link(design_top_module_name)

# --- Clock Configuration ---
# Define clock parameters
clock_port_name = "clk_i"
clock_period_ns = 40
clock_name = "core_clock"

# Create clock signal on the specified port
print(f"Creating clock {clock_name} on port {clock_port_name} with period {clock_period_ns} ns")
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")

# Set the clock as propagated for timing analysis
print("Setting propagated clock")
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# --- Floorplanning ---
print("Performing floorplanning")
floorplan = design.getFloorplan()

# Define die and core areas based on 10um margin
# Assuming a hypothetical square die size for calculation purposes,
# a real design would likely have target core dimensions or utilization.
# Here we define core dimensions based on a target utilization (set later)
# and define die area with a 10um margin around it.
# Since initFloorplan requires explicit core/die rects, we'll define
# a core area based on a conceptual size and calculate the die area from there.
# A 1mm x 1mm core with 10um margin results in 1.02mm x 1.02mm die.
core_size_um = 1000 # Hypothetical core size for margin calculation
margin_um = 10
die_size_um = core_size_um + 2 * margin_um

# Define die area rectangle (from origin 0,0)
die_area = odb.Rect(design.micronToDBU(0), design.micronToDBU(0),
    design.micronToDBU(die_size_um), design.micronToDBU(die_size_um))

# Define core area rectangle (with margin)
core_area = odb.Rect(design.micronToDBU(margin_um), design.micronToDBU(margin_um),
    design.micronToDBU(die_size_um - margin_um), design.micronToDBU(die_size_um - margin_um))

# Find the site from the technology LEF
site = floorplan.findSite("site") # Replace "site" with the actual site name from your LEF

# Initialize the floorplan with the defined areas and site
floorplan.initFloorplan(die_area, core_area, site)

# Create placement tracks
floorplan.makeTracks()

# Set target core utilization for placement (applied later)
design.evalTclString("set core_utilization 0.50")
print("Floorplan initialized with 10um margin and target utilization 50%")

# --- I/O Pin Placement ---
print("Placing I/O pins")
io_placer = design.getIOPlacer()
# Get routing layers for pin placement (replace with actual layer names if needed)
metal8_layer = design.getTech().getDB().getTech().findLayer("metal8")
metal9_layer = design.getTech().getDB().getTech().findLayer("metal9")

if metal8_layer and metal9_layer:
    # Add layers for horizontal and vertical pin placement
    io_placer.addHorLayer(metal8_layer)
    io_placer.addVerLayer(metal9_layer)

    # Run I/O pin placement (using annealing with random mode)
    io_placer.runAnnealing(True) # True for random mode
    print("I/O pins placed on metal8 (horizontal) and metal9 (vertical)")
else:
    print("Warning: metal8 or metal9 layer not found. Skipping I/O pin placement.")


# --- Macro Placement ---
# Check if there are macros in the design
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    print(f"Found {len(macros)} macros. Performing macro placement.")
    mpl = design.getMacroPlacer()
    block = design.getBlock()
    core = block.getCoreArea()

    # Define halo size around macros
    macro_halo_um = 5.0

    # Define fence region as the core area
    fence_lx = block.dbuToMicrons(core.xMin())
    fence_ly = block.dbuToMicrons(core.yMin())
    fence_ux = block.dbuToMicrons(core.xMax())
    fence_uy = block.dbuToMicrons(core.yMax())

    # Run macro placement
    # Note: Direct control for minimum spacing between macros (5um requested)
    # is not a direct parameter in this API call. The halo setting helps
    # push standard cells away from macros, and overall placement density/params
    # influence macro separation.
    mpl.place(
        # Parameters are similar to Example 1; adjust as needed for your design
        num_threads = 64,
        max_num_macro = len(macros), # Place all macros
        halo_width = macro_halo_um,
        halo_height = macro_halo_um,
        fence_lx = fence_lx,
        fence_ly = fence_ly,
        fence_ux = fence_ux,
        fence_uy = fence_uy,
        # Other parameters left at potential default/example values
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
        target_util = design.evalTclString("expr $::floorplan_core_utilization"), # Use core_utilization setting
        target_dead_space = 0.05,
        min_ar = 0.33,
        snap_layer = 4, # Snap to metal4 tracks
        bus_planning_flag = False,
        report_directory = ""
    )
    print(f"Macro placement complete with {macro_halo_um}um halo")
else:
    print("No macros found. Skipping macro placement.")

# --- Global Placement ---
print("Performing global placement")
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Not timing driven in this flow step
gpl.setRoutabilityDrivenMode(True) # Enable routability driven placement
gpl.setUniformTargetDensityMode(True)
# Set initial placement iterations as requested (30)
gpl.setInitialPlaceMaxIter(30)
gpl.setInitDensityPenalityFactor(0.05)

# Run global placement
gpl.doInitialPlace(threads = 4) # Use 4 threads
gpl.doNesterovPlace(threads = 4) # Use 4 threads
gpl.reset()
print("Global placement complete")

# --- Detailed Placement (Initial) ---
print("Performing initial detailed placement")
opendp = design.getOpendp()

# Remove filler cells before detailed placement if they exist from a previous run
# This step is often needed if design is loaded from a DEF with fillers
opendp.removeFillers()

# Set maximum displacement for detailed placement (0um for x and y)
max_disp_um_x = 0
max_disp_um_y = 0
# Convert micrometers to DBU (Database Units) for the API call
max_disp_x_dbu = int(design.micronToDBU(max_disp_um_x))
max_disp_y_dbu = int(design.micronToDBU(max_disp_um_y))

# Run detailed placement
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False) # "" for default cell list, False for non-CTS mode
print(f"Initial detailed placement complete (max displacement X={max_disp_um_x}um, Y={max_disp_um_y}um)")

# --- Clock Tree Synthesis (CTS) ---
print("Performing Clock Tree Synthesis (CTS)")
# Ensure propagated clock is set (redundant but safe after placement)
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Set unit resistance and capacitance for wires
rc_resistance = 0.0435
rc_capacitance = 0.0817
print(f"Setting wire RC: Resistance={rc_resistance}, Capacitance={rc_capacitance}")
design.evalTclString(f"set_wire_rc -clock -resistance {rc_resistance} -capacitance {rc_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {rc_resistance} -capacitance {rc_capacitance}")

# Get the CTS tool object
cts = design.getTritonCts()

# Set clock buffer cells to be used
buffer_cell_name = "BUF_X3" # Replace with actual buffer cell name if different
print(f"Setting CTS buffers to: {buffer_cell_name}")
cts.setBufferList(buffer_cell_name)
cts.setRootBuffer(buffer_cell_name) # Use specified buffer for root
cts.setSinkBuffer(buffer_cell_name) # Use specified buffer for sinks

# Run CTS
cts.runTritonCts()
print("CTS complete")

# --- Detailed Placement (Post-CTS) ---
print("Performing post-CTS detailed placement")
# Remove filler cells again before post-CTS detailed placement
opendp.removeFillers()
# Rerun detailed placement with the same constraints (0um displacement)
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
print("Post-CTS detailed placement complete")


# --- Power Delivery Network (PDN) Construction ---
print("Constructing Power Delivery Network (PDN)")
pdngen = design.getPdnGen()
block = design.getBlock()

# Set power and ground nets as special nets
# Find or create VDD and VSS nets
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

# Create nets if they don't exist
if VDD_net is None:
    print("Creating VDD net")
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSigType("POWER") # Set signal type
    VDD_net.setSpecial() # Mark as special net
if VSS_net is None:
    print("Creating VSS net")
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSigType("GROUND") # Set signal type
    VSS_net.setSpecial() # Mark as special net

# Configure global power/ground connections for standard cells
# Connect instances' VDD/VSS pins to the global VDD/VSS nets
# Assumes default pin names VDD and VSS
print("Adding global power/ground connections")
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
# Apply the global connections
block.globalConnect()

# Define the core voltage domain
print("Setting core voltage domain")
pdngen.setCoreDomain(power = VDD_net, switched_power = None, ground = VSS_net, secondary = list())

# Get the core voltage domain object
core_domain = pdngen.findDomain("Core")
if not core_domain:
    print("Error: Core domain not found.")
    exit()

# Create the main core power grid structure
print("Creating core grid")
pdngen.makeCoreGrid(
    domain = core_domain,
    name = "core_grid",
    starts_with = pdn.GROUND # Start with ground net stripe
)
core_grid = pdngen.findGrid("core_grid")
if not core_grid:
    print("Error: Core grid not found.")
    exit()


# Get required metal layers (replace with actual layer names if needed)
metal1_layer = design.getTech().getDB().getTech().findLayer("metal1")
metal4_layer = design.getTech().getDB().getTech().findLayer("metal4")
metal5_layer = design.getTech().getDB().getTech().findLayer("metal5")
metal6_layer = design.getTech().getDB().getTech().findLayer("metal6")
metal7_layer = design.getTech().getDB().getTech().findLayer("metal7")
metal8_layer = design.getTech().getDB().getTech().findLayer("metal8")

if not all([metal1_layer, metal4_layer, metal5_layer, metal6_layer, metal7_layer, metal8_layer]):
    print("Error: One or more required metal layers not found. Skipping PDN construction.")
else:
    # --- Core/Standard Cell PDN ---
    print("Adding core/standard cell PDN features")
    # Add power rings around core area
    ring_width_um_core = 5
    ring_spacing_um_core = 5
    print(f"Adding core rings on {metal7_layer.getName()} and {metal8_layer.getName()} ({ring_width_um_core}um W, {ring_spacing_um_core}um S)")
    pdngen.makeRing(
        grid = core_grid,
        layer0 = metal7_layer, width0 = design.micronToDBU(ring_width_um_core), spacing0 = design.micronToDBU(ring_spacing_um_core),
        layer1 = metal8_layer, width1 = design.micronToDBU(ring_width_um_core), spacing1 = design.micronToDBU(ring_spacing_um_core),
        starts_with = pdn.GRID, # Align to grid pattern
        offset = [design.micronToDBU(0)]*4, # 0um offset from core boundary
        pad_offset = [design.micronToDBU(0)]*4, # 0um pad offset
        extend = False, # Do not extend rings
        pad_pin_layers = list(), # No specific pad pin layers needed for rings
        nets = list() # Apply to both VDD/VSS in the grid
    )

    # Add horizontal power straps following standard cell power pins (M1)
    strap_width_m1_um = 0.07
    print(f"Adding standard cell followpin straps on {metal1_layer.getName()} ({strap_width_m1_um}um W)")
    pdngen.makeFollowpin(
        grid = core_grid,
        layer = metal1_layer,
        width = design.micronToDBU(strap_width_m1_um),
        extend = pdn.CORE # Extend across the core area
    )

    # Add power straps on M4
    strap_width_m4_um = 1.2
    strap_spacing_m4_um = 1.2
    strap_pitch_m4_um = 6
    print(f"Adding straps on {metal4_layer.getName()} ({strap_width_m4_um}um W, {strap_spacing_m4_um}um S, {strap_pitch_m4_um}um P)")
    pdngen.makeStrap(
        grid = core_grid,
        layer = metal4_layer,
        width = design.micronToDBU(strap_width_m4_um),
        spacing = design.micronToDBU(strap_spacing_m4_um),
        pitch = design.micronToDBU(strap_pitch_m4_um),
        offset = design.micronToDBU(0), # 0um offset
        number_of_straps = 0, # Auto-calculate number
        snap = False, # Do not snap to grid explicitly (pitch defines placement)
        starts_with = pdn.GRID, # Align to grid pattern
        extend = pdn.CORE, # Extend across the core area
        nets = list() # Apply to both VDD/VSS in the grid
    )

    # Add power straps on M7 and M8
    strap_width_m7m8_um = 1.4
    strap_spacing_m7m8_um = 1.4
    strap_pitch_m7m8_um = 10.8
    print(f"Adding straps on {metal7_layer.getName()} and {metal8_layer.getName()} ({strap_width_m7m8_um}um W, {strap_spacing_m7m8_um}um S, {strap_pitch_m7m8_um}um P)")
    pdngen.makeStrap(
        grid = core_grid,
        layer = metal7_layer,
        width = design.micronToDBU(strap_width_m7m8_um),
        spacing = design.micronToDBU(strap_spacing_m7m8_um),
        pitch = design.micronToDBU(strap_pitch_m7m8_um),
        offset = design.micronToDBU(0),
        number_of_straps = 0,
        snap = False,
        starts_with = pdn.GRID,
        extend = pdn.RINGS, # Extend to connect to the core rings
        nets = list()
    )
    pdngen.makeStrap(
        grid = core_grid,
        layer = metal8_layer,
        width = design.micronToDBU(strap_width_m7m8_um),
        spacing = design.micronToDBU(strap_spacing_m7m8_um),
        pitch = design.micronToDBU(strap_pitch_m7m8_um),
        offset = design.micronToDBU(0),
        number_of_straps = 0,
        snap = False,
        starts_with = pdn.GRID,
        extend = pdn.BOUNDARY, # Extend to the boundary
        nets = list()
    )

    # --- Macro PDN (if macros exist) ---
    if len(macros) > 0:
        print("Adding macro-specific PDN features")
        ring_width_um_macro = 2
        ring_spacing_um_macro = 2
        strap_width_macro_um = 1.2
        strap_spacing_macro_um = 1.2
        strap_pitch_macro_um = 6

        # Iterate through each macro instance
        for i, macro_inst in enumerate(macros):
            macro_inst_name = macro_inst.getName()
            macro_grid_name = f"macro_grid_{macro_inst_name}_{i}"
            print(f"Creating macro grid for {macro_inst_name} ({macro_grid_name})")

            # Create a power grid specific to this macro instance
            pdngen.makeInstanceGrid(
                domain = core_domain, # Assign to the core domain
                name = macro_grid_name,
                starts_with = pdn.GROUND,
                inst = macro_inst,
                halo = [design.micronToDBU(0)]*4, # No halo needed for instance grid itself
                pg_pins_to_boundary = True, # Place VDD/VSS pins on boundary
                default_grid = False, # Not the default grid for the domain
                generate_obstructions = [],
                is_bump = False
            )
            macro_grid = pdngen.findGrid(macro_grid_name)
            if not macro_grid:
                print(f"Error: Macro grid {macro_grid_name} not found.")
                continue

            # Add power rings around the macro
            print(f"Adding macro rings on {metal5_layer.getName()} and {metal6_layer.getName()} ({ring_width_um_macro}um W, {ring_spacing_um_macro}um S)")
            pdngen.makeRing(
                grid = macro_grid,
                layer0 = metal5_layer, width0 = design.micronToDBU(ring_width_um_macro), spacing0 = design.micronToDBU(ring_spacing_um_macro),
                layer1 = metal6_layer, width1 = design.micronToDBU(ring_width_um_macro), spacing1 = design.micronToDBU(ring_spacing_um_macro),
                starts_with = pdn.GRID,
                offset = [design.micronToDBU(0)]*4,
                pad_offset = [design.micronToDBU(0)]*4,
                extend = False,
                pad_pin_layers = list(),
                nets = list()
            )

            # Add power straps within the macro grid (M5, M6)
            print(f"Adding macro straps on {metal5_layer.getName()} and {metal6_layer.getName()} ({strap_width_macro_um}um W, {strap_spacing_macro_um}um S, {strap_pitch_macro_um}um P)")
            pdngen.makeStrap(
                grid = macro_grid,
                layer = metal5_layer,
                width = design.micronToDBU(strap_width_macro_um),
                spacing = design.micronToDBU(strap_spacing_macro_um),
                pitch = design.micronToDBU(strap_pitch_macro_um),
                offset = design.micronToDBU(0),
                number_of_straps = 0,
                snap = True, # Snap to grid defined by pitch
                starts_with = pdn.GRID,
                extend = pdn.RINGS, # Extend to macro rings
                nets = list()
            )
            pdngen.makeStrap(
                grid = macro_grid,
                layer = metal6_layer,
                width = design.micronToDBU(strap_width_macro_um),
                spacing = design.micronToDBU(strap_spacing_macro_um),
                pitch = design.micronToDBU(strap_pitch_macro_um),
                offset = design.micronToDBU(0),
                number_of_straps = 0,
                snap = True,
                starts_with = pdn.GRID,
                extend = pdn.RINGS,
                nets = list()
            )

            # Add via connections between macro grid layers and to core grid layers
            via_cut_pitch_um = 2
            via_cut_pitch_dbu = [design.micronToDBU(via_cut_pitch_um), design.micronToDBU(via_cut_pitch_um)]
            print(f"Adding via connections with cut pitch {via_cut_pitch_um}um")

            # Connections within macro grid (M5-M6)
            pdngen.makeConnect(
                grid = macro_grid,
                layer0 = metal5_layer, layer1 = metal6_layer,
                cut_pitch_x = via_cut_pitch_dbu[0], cut_pitch_y = via_cut_pitch_dbu[1]
            )
            # Connections from macro grid to core grid layers
            pdngen.makeConnect(
                grid = macro_grid,
                layer0 = metal4_layer, layer1 = metal5_layer,
                cut_pitch_x = via_cut_pitch_dbu[0], cut_pitch_y = via_cut_pitch_dbu[1]
            )
            pdngen.makeConnect(
                grid = macro_grid,
                layer0 = metal6_layer, layer1 = metal7_layer,
                cut_pitch_x = via_cut_pitch_dbu[0], cut_pitch_y = via_cut_pitch_dbu[1]
            )

    # --- Core Grid Via Connections ---
    print("Adding via connections for core grid")
    via_cut_pitch_um = 2
    via_cut_pitch_dbu = [design.micronToDBU(via_cut_pitch_um), design.micronToDBU(via_cut_pitch_um)]
    print(f"Adding core grid via connections with cut pitch {via_cut_pitch_um}um")

    # Connections within core grid layers
    pdngen.makeConnect(
        grid = core_grid,
        layer0 = metal1_layer, layer1 = metal4_layer,
        cut_pitch_x = via_cut_pitch_dbu[0], cut_pitch_y = via_cut_pitch_dbu[1]
    )
    pdngen.makeConnect(
        grid = core_grid,
        layer0 = metal4_layer, layer1 = metal7_layer,
        cut_pitch_x = via_cut_pitch_dbu[0], cut_pitch_y = via_cut_pitch_dbu[1]
    )
    pdngen.makeConnect(
        grid = core_grid,
        layer0 = metal7_layer, layer1 = metal8_layer,
        cut_pitch_x = via_cut_pitch_dbu[0], cut_pitch_y = via_cut_pitch_dbu[1]
    )

    # --- Build and Write PDN ---
    print("Building and writing PDN")
    pdngen.checkSetup() # Verify the PDN setup
    pdngen.buildGrids(False) # Build the power grid shapes
    pdngen.writeToDb(True) # Write the generated shapes to the design database
    pdngen.resetShapes() # Clear temporary shapes

    print("PDN construction complete")

    # --- Static IR Drop Analysis ---
    print("Performing static IR drop analysis on VDD net")
    psm_obj = design.getPDNSim()
    # Get the first timing corner for analysis (timing setup is required)
    timing = Timing(design)
    corners = timing.getCorners()
    if not corners:
        print("Error: No timing corners found. Cannot perform IR drop analysis.")
    else:
        # Analyze the VDD power grid
        # The analyzePowerGrid function analyzes the grid connected to the net.
        # It does not have a specific parameter to analyze *only* a single layer like M1.
        # The analysis will include contributions from all connected metal layers (M1-M8 in this case).
        # To focus on M1 drop, one would typically look at the voltage report output
        # and inspect node voltages on the M1 layer.
        # Using FULL source type for comprehensive analysis.
        print(f"Analyzing VDD net using timing corner: {corners[0].getName()}")
        psm_obj.analyzePowerGrid(
            net = VDD_net,
            enable_em = False, # EM analysis disabled
            corner = corners[0],
            use_prev_solution = False,
            source_type = psm.GeneratedSourceType_FULL # Use full current sources
        )
        print("Static IR drop analysis complete for VDD net.")
        # Results are typically written to internal database or report files (not explicitly requested here).
        # Voltage maps can be viewed in GUI or dumped via other commands if needed.


# --- Write Output DEF ---
output_def_file = "PDN.def"
print(f"Writing final DEF file: {output_def_file}")
design.writeDef(output_def_file)
print("Script finished.")