from openroad import Tech, Design, Timing
from pathlib import Path
import odb
import pdn
import drt
import psm

# Initialize OpenROAD objects
tech = Tech()

# --- File Paths Configuration ---
# Set paths to library and design files
# IMPORTANT: Replace with your actual paths
libDir = Path("../Design/your_tech/lib")
lefDir = Path("../Design/your_tech/lef")
designDir = Path("../Design/")

# Define the design name and top module name
# Assuming the verilog file is named your_design.v and the top module is your_design
design_name = "your_design" # Replace with your design file name without extension
design_top_module_name = "your_design" # Replace with your actual top module name

# --- Technology and Library Loading ---
# Read all liberty (.lib) and LEF files from the library directories
libFiles = libDir.glob("*.lib")
techLefFiles = lefDir.glob("*.tech.lef")
lefFiles = lefDir.glob('*.lef')

# Load liberty timing libraries
for libFile in libFiles:
    print(f"Reading liberty file: {libFile.as_posix()}")
    tech.readLiberty(libFile.as_posix())

# Load technology and cell LEF files
for techLefFile in techLefFiles:
    print(f"Reading tech LEF file: {techLefFile.as_posix()}")
    tech.readLef(techLefFile.as_posix())
for lefFile in lefFiles:
    # Skip tech.lef as it's handled separately
    if ".tech.lef" not in lefFile.name:
        print(f"Reading cell LEF file: {lefFile.as_posix()}")
        tech.readLef(lefFile.as_posix())

# --- Design Loading and Linking ---
# Create design object
design = Design(tech)

# Read Verilog netlist
verilogFile = designDir / str(design_name + ".v")
print(f"Reading Verilog netlist: {verilogFile.as_posix()}")
design.readVerilog(verilogFile.as_posix())

# Link the design to resolve instances and nets based on loaded libraries
print(f"Linking design with top module: {design_top_module_name}")
design.link(design_top_module_name)

# Get the core and die area from the design block if already set, otherwise define a default
# Assuming a default die area if none is set in the input LEF/DEF
block = design.getBlock()
if block.getDieArea().isNull():
    # Define a default die area if not provided
    die_width_um = 100.0
    die_height_um = 100.0
    die_area = odb.Rect(design.micronToDBU(0), design.micronToDBU(0),
                        design.micronToDBU(die_width_um), design.micronToDBU(die_height_um))
    block.setDieArea(die_area)
else:
    die_area = block.getDieArea()
    die_width_um = design.dbuToMicrons(die_area.xMax() - die_area.xMin())
    die_height_um = design.dbuToMicrons(die_area.yMax() - die_area.yMin())

# --- Clock Definition ---
clock_period_ns = 40.0
clock_port_name = "clk_i"
clock_name = "core_clock"
# Create clock signal with specified period on the clk_i port
print(f"Creating clock '{clock_name}' on port '{clock_port_name}' with period {clock_period_ns} ns")
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")

# Propagate the clock signal
print("Setting clock as propagated timing clock")
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# --- Floorplanning ---
print("Performing floorplanning")
floorplan = design.getFloorplan()

# Calculate core area based on 10um margin from die boundary
margin_um = 10.0
core_area_llx_um = margin_um
core_area_lly_um = margin_um
core_area_urx_um = die_width_um - margin_um
core_area_ury_um = die_height_um - margin_um

core_area = odb.Rect(design.micronToDBU(core_area_llx_um), design.micronToDBU(core_area_lly_um),
                     design.micronToDBU(core_area_urx_um), design.micronToDBU(core_area_ury_um))

# Find a suitable site (replace "FreePDK45_38x28_10R_NP_162NW_34O" with your technology's site name)
# You might need to inspect your LEF file to find the correct site name
site = floorplan.findSite("your_site_name") # Replace with your site name
if not site:
    print("Warning: Could not find a site. Floorplan initialization might fail.")
    # Attempt to find the first CORE site available
    for s in tech.getDB().getTech().getSites():
        if s.getClass().getName() == "CORE":
            site = s
            print(f"Using CORE site: {site.getName()}")
            break
    if not site:
         raise RuntimeError("Could not find any CORE site in the technology.")


# Initialize floorplan with calculated die and core areas using the found site
print(f"Initializing floorplan with Die Area: {die_area} DBU, Core Area: {core_area} DBU, Site: {site.getName()}")
floorplan.initFloorplan(die_area, core_area, site)

# Create routing tracks based on the floorplan site and layers
print("Making routing tracks")
floorplan.makeTracks()

# --- I/O Pin Placement ---
print("Placing I/O pins")
ioPlacer = design.getIOPlacer()
# Clear default layer preferences
ioPlacer.clearLayers()

# Find metal layers M8 (horizontal) and M9 (vertical)
metal8 = design.getTech().getDB().getTech().findLayer("M8") # Replace "M8" if your layer name is different
metal9 = design.getTech().getDB().getTech().findLayer("M9") # Replace "M9" if your layer name is different

if not metal8 or not metal9:
     raise RuntimeError("Could not find M8 or M9 layer for I/O placement. Check your LEF.")

# Add horizontal and vertical layers for I/O placement
ioPlacer.addHorLayer(metal8)
ioPlacer.addVerLayer(metal9)

# Set parameters for I/O placer (using default annealing parameters)
# Running annealing-based I/O placement
ioPlacer.runAnnealing(True) # True for random mode

# --- Placement ---

# Set target utilization (This is usually a parameter for placement, not floorplanning init)
# The Python API for setting target utilization directly in the main Design object is not common.
# It's often a parameter in the global placer (Replace). Let's set it there.
target_utilization = 0.45
print(f"Setting target utilization for placement: {target_utilization}")
# This parameter is usually controlled within the placer engines, not a global design setting.
# We will rely on the placer settings later.

# Global Placement
print("Performing global placement")
gpl = design.getReplace()
# Set global placement parameters
gpl.setTimingDrivenMode(False) # Example: Not timing-driven
gpl.setRoutabilityDrivenMode(True) # Example: Routability-driven
gpl.setUniformTargetDensityMode(True)
# Set the number of initial placement iterations
gpl.setInitialPlaceMaxIter(30)
# Set the target density (directly related to utilization)
gpl.setTargetDensity(target_utilization) # Use the target utilization here
gpl.setInitDensityPenalityFactor(0.05) # Example penalty factor
# Run global placement
gpl.doInitialPlace(threads = 4) # Use appropriate number of threads
gpl.doNesterovPlace(threads = 4) # Use appropriate number of threads
gpl.reset() # Reset placer state for next stage

# Macro Placement (if macros exist)
# Find macro instances
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    print(f"Found {len(macros)} macros. Performing macro placement.")
    mpl = design.getMacroPlacer()
    block = design.getBlock()

    # Convert bounding box coordinates to DBU
    bbox_llx_um = 32.0
    bbox_lly_um = 32.0
    bbox_urx_um = 55.0
    bbox_ury_um = 60.0

    fence_lx_dbu = design.micronToDBU(bbox_llx_um)
    fence_ly_dbu = design.micronToDBU(bbox_lly_um)
    fence_ux_dbu = design.micronToDBU(bbox_urx_um)
    fence_uy_dbu = design.micronToDBU(bbox_ury_um)

    # Set halo and minimum spacing parameters
    halo_um = 5.0
    min_macro_spacing_um = 5.0 # Note: MacroPlacer API uses different spacing parameters, this is conceptual
    # The specific MacroPlacer API parameters related to min spacing are not directly exposed like a simple 'min_spacing'.
    # Halo is supported directly. We will use the fence region and halo.

    # The mpl.place method used in Example 1 takes fence, halo, etc.
    # Let's use a simplified version if available or adapt from Example 1
    # The `mpl.placeMacrosCornerMaxWl()` API mentioned in the knowledge base
    # seems simpler but pushes macros to corners, not a specific box.
    # Let's stick to the more general `mpl.place` method from Example 1.

    mpl.place(
        num_threads = 64,
        max_num_macro = len(macros), # Place all found macros
        min_num_macro = 0,
        max_num_inst = 0,
        min_num_inst = 0,
        tolerance = 0.1, # Example value
        max_num_level = 2, # Example value
        coarsening_ratio = 10.0, # Example value
        large_net_threshold = 50, # Example value
        signature_net_threshold = 50, # Example value
        halo_width = halo_um, # Set macro halo width
        halo_height = halo_um, # Set macro halo height
        # Use the specified bounding box as the fence region
        fence_lx = bbox_llx_um,
        fence_ly = bbox_lly_um,
        fence_ux = bbox_urx_um,
        fence_uy = bbox_ury_um,
        area_weight = 0.1, # Example weights
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        pin_access_th = 0.0,
        target_util = 0.25, # Target utilization for the macro placement region, adjust if needed
        target_dead_space = 0.05, # Example value
        min_ar = 0.33, # Example aspect ratio
        snap_layer = 4, # Example layer to snap macro pins to grid
        bus_planning_flag = False,
        report_directory = ""
    )

# Detailed Placement
print("Performing detailed placement")
dp = design.getOpendp()

# Remove any potential filler cells from previous stages
dp.removeFillers()

# Set maximum displacement for detailed placement
# 0 um displacement means cells are not allowed to move from their current global placement location
max_disp_x_um = 0.0
max_disp_y_um = 0.0

max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

# Detailed placement requires max displacement in site units, not DBU
# Get the site height and width from the first row
site = design.getBlock().getRows()[0].getSite()
site_width_dbu = site.getWidth()
site_height_dbu = site.getHeight()

# Calculate max displacement in site units
# If site_width_dbu or site_height_dbu is 0, this will cause division by zero.
# Assuming valid site dimensions.
max_disp_x_site_units = int(max_disp_x_dbu / site_width_dbu) if site_width_dbu > 0 else 0
max_disp_y_site_units = int(max_disp_y_dbu / site_height_dbu) if site_height_dbu > 0 else 0


print(f"Detailed placement max displacement: X={max_disp_x_um} um ({max_disp_x_site_units} sites), Y={max_disp_y_um} um ({max_disp_y_site_units} sites)")

# Run detailed placement
dp.detailedPlacement(max_disp_x_site_units, max_disp_y_site_units, "", False) # "" means no specific regions, False for not timing driven

# --- Clock Tree Synthesis (CTS) ---
print("Performing Clock Tree Synthesis (CTS)")
cts = design.getTritonCts()

# Propagate the clock signal again before CTS
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Set RC values for clock and signal nets
rc_resistance = 0.0435
rc_capacitance = 0.0817
print(f"Setting wire RC values - Clock: R={rc_resistance}, C={rc_capacitance}")
print(f"Setting wire RC values - Signal: R={rc_resistance}, C={rc_capacitance}")
design.evalTclString(f"set_wire_rc -clock -resistance {rc_resistance} -capacitance {rc_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {rc_resistance} -capacitance {rc_capacitance}")

# Set clock buffers to use
buffer_name = "BUF_X3" # Replace with the actual name of your BUF_X3 cell in the library
print(f"Setting clock buffers to use: {buffer_name}")
cts.setBufferList(buffer_name)
cts.setRootBuffer(buffer_name) # Use same buffer for root and sinks for simplicity
cts.setSinkBuffer(buffer_name)

# Run CTS
cts.runTritonCts()

# --- Power Delivery Network (PDN) Construction ---
print("Constructing Power Delivery Network (PDN)")
pdngen = design.getPdnGen()

# Set up global power/ground connections
# Find existing power and ground nets or create if needed
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")

# Create VDD/VSS nets if they don't exist and mark them special
if VDD_net is None:
    print("Creating VDD net")
    VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
    VDD_net.setSigType("POWER")
    VDD_net.setSpecial()
if VSS_net is None:
    print("Creating VSS net")
    VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
    VSS_net.setSigType("GROUND")
    VSS_net.setSpecial()

# Connect power pins to global nets (example patterns, adjust if needed)
print("Adding global power/ground connections")
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD.*", net = VDD_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS.*", net = VSS_net, do_connect = True)
design.getBlock().globalConnect()

# Configure core power domain
print("Setting core power domain")
pdngen.setCoreDomain(power = VDD_net,
                     switched_power = None, # Assuming no switched power
                     ground = VSS_net,
                     secondary = []) # Assuming no secondary power nets

# Get metal layers required for PDN
m1 = design.getTech().getDB().getTech().findLayer("M1") # Replace "M1" with actual layer name
m4 = design.getTech().getDB().getTech().findLayer("M4") # Replace "M4" with actual layer name
m5 = design.getTech().getDB().getTech().findLayer("M5") # Replace "M5" with actual layer name
m6 = design.getTech().getDB().getTech().findLayer("M6") # Replace "M6" with actual layer name
m7 = design.getTech().getDB().getTech().findLayer("M7") # Replace "M7" with actual layer name
m8 = design.getTech().getDB().getTech().findLayer("M8") # Replace "M8" with actual layer name

if not all([m1, m4, m5, m6, m7, m8]):
    raise RuntimeError("Could not find all required metal layers (M1, M4, M5, M6, M7, M8) for PDN. Check your LEF.")


# Define PDN parameters in DBU
offset_dbu = design.micronToDBU(0.0) # Offset for all cases
via_cut_pitch_dbu = design.micronToDBU(2.0) # Pitch for vias between grids

# Create the main core grid structure for standard cells
domains = [pdngen.findDomain("Core")]
halo_dbu = [design.micronToDBU(0) for i in range(4)] # No halo needed for the core grid itself

for domain in domains:
    print("Creating core grid for standard cells")
    pdngen.makeCoreGrid(domain = domain,
                        name = "stdcell_grid",
                        starts_with = pdn.GROUND, # Example: Start with ground connection
                        pin_layers = [], # Auto-detect pin layers
                        generate_obstructions = [], # Do not generate obstructions
                        powercell = None,
                        powercontrol = None,
                        powercontrolnetwork = "STAR") # Example network type

# Get the core grid object
stdcell_grid = pdngen.findGrid("stdcell_grid")[0] # makeCoreGrid returns a list

# Configure and add elements to the standard cell grid
print("Adding rings and straps to standard cell grid")

# Core Power Rings (M7 and M8)
ring_width_um = 5.0
ring_spacing_um = 5.0
ring_width_dbu = design.micronToDBU(ring_width_um)
ring_spacing_dbu = design.micronToDBU(ring_spacing_um)
ring_offset_dbu = [offset_dbu for i in range(4)]

pdngen.makeRing(grid = stdcell_grid,
                layer0 = m7, width0 = ring_width_dbu, spacing0 = ring_spacing_dbu,
                layer1 = m8, width1 = ring_width_dbu, spacing1 = ring_spacing_dbu,
                starts_with = pdn.GRID,
                offset = ring_offset_dbu,
                pad_offset = [offset_dbu for i in range(4)], # No specific pad offset
                extend = False, # Do not extend rings beyond core boundary
                pad_pin_layers = [], # No specific pad pin layers needed for core rings
                nets = []) # Connects to all nets in the domain

# Standard Cell Straps (M1, M4, M7)
m1_strap_width_um = 0.07
m4_strap_width_um = 1.2
m4_strap_spacing_um = 1.2
m4_strap_pitch_um = 6.0
m7_strap_width_um = 1.4
m7_strap_spacing_um = 1.4
m7_strap_pitch_um = 10.8

m1_strap_width_dbu = design.micronToDBU(m1_strap_width_um)
m4_strap_width_dbu = design.micronToDBU(m4_strap_width_um)
m4_strap_spacing_dbu = design.micronToDBU(m4_strap_spacing_um)
m4_strap_pitch_dbu = design.micronToDBU(m4_strap_pitch_um)
m7_strap_width_dbu = design.micronToDBU(m7_strap_width_um)
m7_strap_spacing_dbu = design.micronToDBU(m7_strap_spacing_um)
m7_strap_pitch_dbu = design.micronToDBU(m7_strap_pitch_um)

# M1 straps following standard cell pins
pdngen.makeFollowpin(grid = stdcell_grid,
                     layer = m1,
                     width = m1_strap_width_dbu,
                     extend = pdn.CORE) # Extend within the core area

# M4 straps
pdngen.makeStrap(grid = stdcell_grid,
                 layer = m4,
                 width = m4_strap_width_dbu,
                 spacing = m4_strap_spacing_dbu,
                 pitch = m4_strap_pitch_dbu,
                 offset = offset_dbu,
                 number_of_straps = 0, # Auto-calculate
                 snap = True, # Snap to grid
                 starts_with = pdn.GRID,
                 extend = pdn.CORE, # Extend within the core area
                 nets = []) # Connects to all nets in the domain

# M7 straps
pdngen.makeStrap(grid = stdcell_grid,
                 layer = m7,
                 width = m7_strap_width_dbu,
                 spacing = m7_strap_spacing_dbu,
                 pitch = m7_strap_pitch_dbu,
                 offset = offset_dbu,
                 number_of_straps = 0, # Auto-calculate
                 snap = True, # Snap to grid
                 starts_with = pdn.GRID,
                 extend = pdn.RINGS, # Extend up to the rings
                 nets = []) # Connects to all nets in the domain

# Connections (Vias) for standard cell grid
print("Adding connections (vias) for standard cell grid")
# M1 to M4 connections
pdngen.makeConnect(grid = stdcell_grid,
                   layer0 = m1, layer1 = m4,
                   cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu,
                   vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [],
                   split_cuts = {}, dont_use_vias = "")
# M4 to M7 connections
pdngen.makeConnect(grid = stdcell_grid,
                   layer0 = m4, layer1 = m7,
                   cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu,
                   vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [],
                   split_cuts = {}, dont_use_vias = "")
# M7 to M8 connections (for rings)
pdngen.makeConnect(grid = stdcell_grid,
                   layer0 = m7, layer1 = m8,
                   cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu,
                   vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [],
                   split_cuts = {}, dont_use_vias = "")

# Power Grid for Macro blocks (if macros exist)
if len(macros) > 0:
    print(f"Creating power grids for {len(macros)} macros")
    m5_strap_width_um = 1.2
    m5_strap_spacing_um = 1.2
    m5_strap_pitch_um = 6.0
    m6_strap_width_um = 1.2
    m6_strap_spacing_um = 1.2
    m6_strap_pitch_um = 6.0

    m5_strap_width_dbu = design.micronToDBU(m5_strap_width_um)
    m5_strap_spacing_dbu = design.micronToDBU(m5_strap_spacing_um)
    m5_strap_pitch_dbu = design.micronToDBU(m5_strap_pitch_um)
    m6_strap_width_dbu = design.micronToDBU(m6_strap_width_um)
    m6_strap_spacing_dbu = design.micronToDBU(m6_strap_spacing_um)
    m6_strap_pitch_dbu = design.micronToDBU(m6_strap_pitch_um)

    macro_halo_dbu = [design.micronToDBU(halo_um) for i in range(4)]

    for i, macro in enumerate(macros):
        macro_grid_name = f"macro_grid_{i}"
        print(f"Creating grid for macro {macro.getName()}")

        # Create instance grid for the macro
        for domain in domains:
            pdngen.makeInstanceGrid(domain = domain,
                                    name = macro_grid_name,
                                    starts_with = pdn.GROUND, # Example: Start with ground
                                    inst = macro,
                                    halo = macro_halo_dbu,
                                    pg_pins_to_boundary = True, # Connect PG pins to macro boundary
                                    default_grid = False, # Not the default grid
                                    generate_obstructions = [],
                                    is_bump = False)

        macro_grid = pdngen.findGrid(macro_grid_name)[0]

        # Add straps to the macro grid (M5, M6)
        print(f"Adding straps to macro grid {macro_grid_name}")
        # M5 straps
        pdngen.makeStrap(grid = macro_grid,
                         layer = m5,
                         width = m5_strap_width_dbu,
                         spacing = m5_strap_spacing_dbu,
                         pitch = m5_strap_pitch_dbu,
                         offset = offset_dbu,
                         number_of_straps = 0,
                         snap = True,
                         starts_with = pdn.GRID,
                         extend = pdn.CORE, # Extend within the macro core
                         nets = [])

        # M6 straps
        pdngen.makeStrap(grid = macro_grid,
                         layer = m6,
                         width = m6_strap_width_dbu,
                         spacing = m6_strap_spacing_dbu,
                         pitch = m6_strap_pitch_dbu,
                         offset = offset_dbu,
                         number_of_straps = 0,
                         snap = True,
                         starts_with = pdn.GRID,
                         extend = pdn.CORE, # Extend within the macro core
                         nets = [])

        # Connections (Vias) for macro grid
        print(f"Adding connections (vias) for macro grid {macro_grid_name}")
        # Connect from core grid M4 to macro grid M5
        pdngen.makeConnect(grid = macro_grid,
                           layer0 = m4, layer1 = m5,
                           cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu,
                           vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [],
                           split_cuts = {}, dont_use_vias = "")
        # Connect macro grid M5 to M6
        pdngen.makeConnect(grid = macro_grid,
                           layer0 = m5, layer1 = m6,
                           cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu,
                           vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [],
                           split_cuts = {}, dont_use_vias = "")
        # Connect macro grid M6 back to core grid M7
        pdngen.makeConnect(grid = macro_grid,
                           layer0 = m6, layer1 = m7,
                           cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu,
                           vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [],
                           split_cuts = {}, dont_use_vias = "")

# Generate the final power delivery network
print("Building and writing PDN to database")
pdngen.checkSetup() # Verify configuration
pdngen.buildGrids(False) # Build the power grid (False for no debug)
pdngen.writeToDb(True, ) # Write power grid to the design database (True to clear previous shapes)
pdngen.resetShapes() # Reset temporary shapes

# --- Post-PDN Analysis: Static IR Drop ---
print("Performing static IR drop analysis on VDD net")
psm_obj = design.getPDNSim()
timing = Timing(design)

# Set the target net for IR drop analysis (VDD)
psm_obj.setNet(VDD_net)

# Define the source types (e.g., standard cells, straps, bumps)
# Using FULL source type for comprehensive analysis
source_types = [psm.GeneratedSourceType_FULL,
    psm.GeneratedSourceType_STRAPS,
    psm.GeneratedSourceType_BUMPS]
source_type = source_types[0] # Use FULL source type

# Get the first corner for analysis (assuming default corner exists)
analysis_corner = timing.getCorners()[0] if timing.getCorners() else None

if analysis_corner:
    # Analyze VDD power grid IR drop
    psm_obj.analyzePowerGrid(net = VDD_net,
        enable_em = False, # Disable electromigration analysis
        corner = analysis_corner,
        use_prev_solution = False, # Do not use previous solution
        em_file = "", # No EM file needed if disabled
        error_file = "irdrop_errors.log", # Log file for errors
        voltage_source_file = "", # Optional: file for external voltage sources
        voltage_file = "irdrop_voltage.rpt", # Output file for voltage report
        source_type = source_type) # Specify source type

    print("Static IR drop analysis complete.")
    print(f"Voltage report saved to irdrop_voltage.rpt (if analysis ran successfully)")
    print(f"Errors logged to irdrop_errors.log (if any)")
else:
    print("Warning: No timing corner found. Skipping static IR drop analysis.")


# --- Output ---
# Write DEF file after PDN
output_def_file = "PDN.def"
print(f"Writing DEF file: {output_def_file}")
design.writeDef(output_def_file)

# Note: The prompt did not ask for global/detailed routing or final DEF/Verilog after PDN.
# The script stops after PDN and IR drop analysis as requested.

print("Script finished.")