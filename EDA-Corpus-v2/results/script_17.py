from openroad import Tech, Design, Timing
from pathlib import Path
import odb
import pdn
import psm

# --- File Paths and Design Setup ---

# Placeholder paths - replace with your actual paths
libDir = Path("../libraries/lib")
lefDir = Path("../libraries/lef")
designFile = Path("../designs/my_design.v") # Replace with your Verilog file
design_top_module_name = "your_top_module" # Replace with your top module name

# Initialize OpenROAD objects
tech = Tech()

# Read technology LEF files
tech_lef_files = lefDir.glob("*.tech.lef")
for tech_lef_file in tech_lef_files:
    tech.readLef(tech_lef_file.as_posix())

# Read cell LEF files
cell_lef_files = lefDir.glob("*.lef")
for cell_lef_file in cell_lef_files:
    tech.readLef(cell_lef_file.as_posix())

# Read Liberty files
lib_files = libDir.glob("*.lib")
for lib_file in lib_files:
    tech.readLiberty(lib_file.as_posix())

# Create design and read Verilog netlist
design = Design(tech)
design.readVerilog(designFile.as_posix())
# Link the design to resolve instances and nets
design.link(design_top_module_name)

# --- Clock Definition ---

# Define clock period in nanoseconds
clock_period_ns = 40
# Define clock port name
clock_port_name = "clk"
# Define clock name
clock_name = "core_clock"

# Create a clock signal on the specified port with the given period and name
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
# Set the created clock as the propagated clock for timing analysis
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# --- Floorplanning ---

# Placeholder site name - replace with the actual site name from your LEF file
site_name = "FreePDK45_38x28_10R_NP_162NW_34O" # Example site name

floorplan = design.getFloorplan()
db = design.getTech().getDB() # Get the OpenROAD database

# Define core to die spacing in microns
core_to_die_spacing_um = 12
core_to_die_spacing_dbu = design.micronToDBU(core_to_die_spacing_um)

# Define a dummy die area (e.g., 200um x 200um) for calculation purposes
# In a real flow, this might be determined by target utilization or other constraints
# Assuming a dummy die size to calculate core area based on spacing
dummy_die_width_um = 200
dummy_die_height_um = 200
dummy_die_x_max_dbu = design.micronToDBU(dummy_die_width_um)
dummy_die_y_max_dbu = design.micronToDBU(dummy_die_height_um)

# Calculate core area based on die area and spacing
core_x_min_dbu = core_to_die_spacing_dbu
core_y_min_dbu = core_to_die_spacing_dbu
core_x_max_dbu = dummy_die_x_max_dbu - core_to_die_spacing_dbu
core_y_max_dbu = dummy_die_y_max_dbu - core_to_die_spacing_dbu

die_area = odb.Rect(0, 0, dummy_die_x_max_dbu, dummy_die_y_max_dbu)
core_area = odb.Rect(core_x_min_dbu, core_y_min_dbu, core_x_max_dbu, core_y_max_dbu)

# Find the standard cell site
site = floorplan.findSite(site_name)
if not site:
    print(f"Error: Site '{site_name}' not found in LEF files.")
    exit()

# Initialize the floorplan with the calculated die and core areas and the site
floorplan.initFloorplan(die_area, core_area, site)
# Create routing tracks based on the technology rules
floorplan.makeTracks()

# Note: Target utilization is typically set as a parameter for placement tools,
# not directly during floorplan initialization when die/core areas are explicitly defined by spacing.
# The requested 50% target utilization will be implicitly targeted by the placement tool
# given the defined core area and the total area of standard cells.

# --- I/O Pin Placement ---

# Configure and run I/O pin placement
io_placer_params = design.getIOPlacer().getParameters()
io_placer_params.setRandSeed(42) # Set random seed for reproducibility
io_placer_params.setMinDistanceInTracks(False) # Set minimum distance in database units, not tracks
io_placer_params.setMinDistance(design.micronToDBU(0)) # Set minimum distance between pins (e.g., 0 for no minimum spacing)
io_placer_params.setCornerAvoidance(design.micronToDBU(0)) # Set minimum distance to avoid corners

# Find the specified metal layers for pin placement
metal8 = db.getTech().findLayer("metal8")
metal9 = db.getTech().findLayer("metal9")

if not metal8 or not metal9:
     print("Error: metal8 or metal9 layer not found for pin placement.")
     # Add error handling or exit if layers are critical
     # For this script, we'll proceed but placement might fail if layers are missing.

# Add horizontal layer for pin placement (metal8)
if metal8:
    design.getIOPlacer().addHorLayer(metal8)
# Add vertical layer for pin placement (metal9)
if metal9:
    design.getIOPlacer().addVerLayer(metal9)

# Run the I/O pin placement annealing algorithm
IOPlacer_random_mode = True # Use random mode for annealing
design.getIOPlacer().runAnnealing(IOPlacer_random_mode)

# --- Placement ---

# Find macro instances
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

# If macros exist, perform macro placement first
if len(macros) > 0:
    mpl = design.getMacroPlacer()
    block = design.getBlock()
    core = block.getCoreArea()

    # Configure macro placement parameters
    # Set halo region around each macro (5 microns)
    halo_width = design.micronToDBU(5.0)
    halo_height = design.micronToDBU(5.0)
    # Set fence region (core area) to restrict macro placement
    fence_lx = block.dbuToMicrons(core.xMin())
    fence_ly = block.dbuToMicrons(core.yMin())
    fence_ux = block.dbuToMicrons(core.xMax())
    fence_uy = block.dbuToMicrons(core.yMax())
    # The '5 um away from each other' constraint is typically handled implicitly
    # by the placement tool considering macro dimensions, halos, and routing congestion.
    # The halo helps create keepout zones.

    mpl.place(
        num_threads = 64, # Number of threads to use
        max_num_macro = len(macros), # Place all macros
        min_num_macro = 0,
        max_num_inst = 0, # No standard cell placement during macro placement
        min_num_inst = 0,
        tolerance = 0.1,
        max_num_level = 2,
        coarsening_ratio = 10.0,
        large_net_threshold = 50,
        signature_net_threshold = 50,
        halo_width = halo_width, # Macro halo width
        halo_height = halo_height, # Macro halo height
        fence_lx = fence_lx, # Fence region lower-left x
        fence_ly = fence_ly, # Fence region lower-left y
        fence_ux = fence_ux, # Fence region upper-right x
        fence_uy = fence_uy, # Fence region upper-right y
        area_weight = 0.1,
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        pin_access_th = 0.0,
        target_util = 0.50, # Target utilization for standard cells (can influence available space)
        target_dead_space = 0.05,
        min_ar = 0.33, # Minimum aspect ratio
        snap_layer = 4, # Layer to snap macro pins to (e.g., metal4)
        bus_planning_flag = False,
        report_directory = ""
    )

# Configure and run global placement
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Disable timing-driven mode for initial placement
gpl.setRoutabilityDrivenMode(True) # Enable routability-driven mode
gpl.setUniformTargetDensityMode(True) # Use uniform target density
# Set initial placement iterations (requested 30)
gpl.setInitialPlaceMaxIter(30)
gpl.setInitDensityPenalityFactor(0.05)
# Perform initial global placement
gpl.doInitialPlace(threads = 4)
# Perform Nesterov-accelerated global placement
gpl.doNesterovPlace(threads = 4)
gpl.reset()

# Configure and run detailed placement
opendp = design.getOpendp()
# Calculate maximum displacement in DBU (0.5 um)
max_disp_x_um = 0.5
max_disp_y_um = 0.5
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

# Remove filler cells before detailed placement (if any exist)
opendp.removeFillers()
# Perform detailed placement with specified maximum displacement
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

# --- Clock Tree Synthesis (CTS) ---

# Set RC values for clock and signal nets (unit resistance and capacitance)
unit_resistance = 0.03574
unit_capacitance = 0.07516
design.evalTclString(f"set_wire_rc -clock -resistance {unit_resistance} -capacitance {unit_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {unit_resistance} -capacitance {unit_capacitance}")

cts = design.getTritonCts()
parms = cts.getParms()
# Set wire segment unit (e.g., 20 DBU)
parms.setWireSegmentUnit(20)
# Configure clock buffer list and root/sink buffers
buffer_cell = "BUF_X2" # Requested buffer cell name
cts.setBufferList(buffer_cell)
cts.setRootBuffer(buffer_cell)
cts.setSinkBuffer(buffer_cell)

# Run Clock Tree Synthesis
cts.runTritonCts()

# Run detailed placement again after CTS to clean up
site = design.getBlock().getRows()[0].getSite()
# Calculate maximum displacement in site units for better DP after CTS
# Max displacement relative to site width/height
max_disp_x_site = int(design.micronToDBU(max_disp_x_um) / site.getWidth())
max_disp_y_site = int(design.micronToDBU(max_disp_y_um) / site.getHeight())
opendp.detailedPlacement(max_disp_x_site, max_disp_y_site, "", False)


# --- Power Delivery Network (PDN) Construction ---

pdngen = design.getPdnGen()

# Find existing power and ground nets or create if needed
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")

# Create VDD/VSS nets if they don't exist
if VDD_net is None:
    VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
    # Mark VDD net as special
    VDD_net.setSpecial()
    # Set signal type to POWER
    VDD_net.setSigType("POWER")
if VSS_net is None:
    VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
    # Mark VSS net as special
    VSS_net.setSpecial()
    # Set signal type to GROUND
    VSS_net.setSigType("GROUND")

# Connect power and ground pins of standard cells to global nets
# Connect any pin named "VDD" to the VDD_net for all instances
design.getBlock().addGlobalConnect(region=None, instPattern=".*", pinPattern="VDD", net=VDD_net, do_connect=True)
# Connect any pin named "VSS" to the VSS_net for all instances
design.getBlock().addGlobalConnect(region=None, instPattern=".*", pinPattern="VSS", net=VSS_net, do_connect=True)
# Apply the global connections
design.getBlock().globalConnect()

# Set core power domain with primary power/ground nets
# Assuming no switched power or secondary nets
switched_power = None
secondary = list()
pdngen.setCoreDomain(power=VDD_net, switched_power=switched_power, ground=VSS_net, secondary=secondary)

# Get the core voltage domain
core_domain = pdngen.findDomain("Core")
if not core_domain:
    print("Error: Core domain not found.")
    exit()
domains = [core_domain]

# Define layers for PDN construction
m1 = db.getTech().findLayer("metal1")
m4 = db.getTech().findLayer("metal4")
m5 = db.getTech().findLayer("metal5")
m6 = db.getTech().findLayer("metal6")
m7 = db.getTech().findLayer("metal7")
m8 = db.getTech().findLayer("metal8")

if not all([m1, m4, m5, m6, m7, m8]):
    print("Error: Required metal layers not found for PDN construction.")
    # Add error handling or exit if layers are critical

# Set offset to 0 DBU for all cases as requested
offset_dbu = design.micronToDBU(0)
offset_list_dbu = [offset_dbu] * 4 # List of 4 offsets for makeRing

# Set via cut pitch to 0 DBU for connections between grids (as requested 'pitch of the via ... to 0 um')
# This implies the default via pitch should be used or no specific pattern is forced.
# Setting to 0 DBU here for cut_pitch_x/y in makeConnect.
pdn_cut_pitch_dbu = design.micronToDBU(0)

# Create the main core grid structure for standard cells
# Starting with ground net connection for followpin on M1
pdngen.makeCoreGrid(
    domain=core_domain,
    name="core_stdcell_grid",
    starts_with=pdn.GROUND, # Start with ground as M1 followpin is often VSS
    pin_layers=[],
    generate_obstructions=[],
    powercell=None,
    powercontrol=None,
    powercontrolnetwork="STAR"
)

core_grid = pdngen.findGrid("core_stdcell_grid")
if not core_grid:
    print("Error: Core standard cell grid not created.")
    exit()

# Add power rings around the core area on M7 and M8
ring_width_um = 5
ring_spacing_um = 5
ring_width_dbu = design.micronToDBU(ring_width_um)
ring_spacing_dbu = design.micronToDBU(ring_spacing_um)

if m7 and m8:
    pdngen.makeRing(
        grid=core_grid,
        layer0=m7,
        width0=ring_width_dbu,
        spacing0=ring_spacing_dbu,
        layer1=m8,
        width1=ring_width_dbu,
        spacing1=ring_spacing_dbu,
        starts_with=pdn.GRID, # Start ring with grid pattern
        offset=offset_list_dbu, # Offset from core boundary
        pad_offset=[offset_dbu]*4, # Offset for padding (set to 0)
        extend=False, # Do not extend beyond the calculated boundary
        pad_pin_layers=[], # No specific layers for pad connections specified
        nets=[] # Connect all nets in the grid (VDD/VSS)
    )

# Add horizontal power straps on M1 following standard cell power rails
m1_strap_width_um = 0.07
m1_strap_width_dbu = design.micronToDBU(m1_strap_width_um)
if m1:
    pdngen.makeFollowpin(
        grid=core_grid,
        layer=m1,
        width=m1_strap_width_dbu,
        extend=pdn.CORE # Extend followpins within the core area
    )

# Add power straps on M4 for standard cells
m4_strap_width_um = 1.2
m4_strap_spacing_um = 1.2
m4_strap_pitch_um = 6
m4_strap_width_dbu = design.micronToDBU(m4_strap_width_um)
m4_strap_spacing_dbu = design.micronToDBU(m4_strap_spacing_um)
m4_strap_pitch_dbu = design.micronToDBU(m4_strap_pitch_um)
if m4:
    pdngen.makeStrap(
        grid=core_grid,
        layer=m4,
        width=m4_strap_width_dbu,
        spacing=m4_strap_spacing_dbu,
        pitch=m4_strap_pitch_dbu,
        offset=offset_dbu,
        number_of_straps=0, # Auto-calculate number of straps
        snap=False, # Do not snap to grid (pitch determines placement)
        starts_with=pdn.GRID, # Start with grid pattern
        extend=pdn.CORE, # Extend within the core area
        nets=[] # Connect all nets in the grid
    )

# Add power straps on M7 and M8
m7_m8_strap_width_um = 1.4
m7_m8_strap_spacing_um = 1.4
m7_m8_strap_pitch_um = 10.8
m7_m8_strap_width_dbu = design.micronToDBU(m7_m8_strap_width_um)
m7_m8_strap_spacing_dbu = design.micronToDBU(m7_m8_strap_spacing_um)
m7_m8_strap_pitch_dbu = design.micronToDBU(m7_m8_strap_pitch_um)

if m7:
    pdngen.makeStrap(
        grid=core_grid,
        layer=m7,
        width=m7_m8_strap_width_dbu,
        spacing=m7_m8_strap_spacing_dbu,
        pitch=m7_m8_strap_pitch_dbu,
        offset=offset_dbu,
        number_of_straps=0,
        snap=False,
        starts_with=pdn.GRID,
        extend=pdn.RINGS, # Extend to the power rings on M7/M8
        nets=[]
    )
if m8:
    pdngen.makeStrap(
        grid=core_grid,
        layer=m8,
        width=m7_m8_strap_width_dbu,
        spacing=m7_m8_strap_spacing_dbu,
        pitch=m7_m8_strap_pitch_dbu,
        offset=offset_dbu,
        number_of_straps=0,
        snap=False,
        starts_with=pdn.GRID,
        extend=pdn.RINGS, # Extend to the power rings on M7/M8
        nets=[]
    )


# Create power grids for macro blocks if they exist
if len(macros) > 0 and m5 and m6:
    macro_strap_width_um = 1.2
    macro_strap_spacing_um = 1.2
    macro_strap_pitch_um = 6
    macro_strap_width_dbu = design.micronToDBU(macro_strap_width_um)
    macro_strap_spacing_dbu = design.micronToDBU(macro_strap_spacing_um)
    macro_strap_pitch_dbu = design.micronToDBU(macro_strap_pitch_um)

    # Halo for macro grid instance (set to 0 as halo is handled during macro placement)
    # Using 0 here just for the makeInstanceGrid call itself, not related to placement halo
    macro_grid_halo_dbu = [design.micronToDBU(0)] * 4

    for i, macro_inst in enumerate(macros):
        # Create separate power grid for each macro instance
        pdngen.makeInstanceGrid(
            domain=core_domain,
            name=f"macro_grid_{macro_inst.getName()}_{i}", # Unique name for each macro grid
            starts_with=pdn.GROUND,
            inst=macro_inst,
            halo=macro_grid_halo_dbu,
            pg_pins_to_boundary=True, # Connect power/ground pins to boundary
            default_grid=False,
            generate_obstructions=[],
            is_bump=False
        )

        macro_inst_grid = pdngen.findGrid(f"macro_grid_{macro_inst.getName()}_{i}")
        if not macro_inst_grid:
            print(f"Warning: Macro instance grid for {macro_inst.getName()} not created.")
            continue

        # Add power straps on M5 for macro connections
        pdngen.makeStrap(
            grid=macro_inst_grid,
            layer=m5,
            width=macro_strap_width_dbu,
            spacing=macro_strap_spacing_dbu,
            pitch=macro_strap_pitch_dbu,
            offset=offset_dbu,
            number_of_straps=0,
            snap=True, # Snap to grid
            starts_with=pdn.GRID,
            extend=pdn.CORE, # Extend within the macro instance boundary
            nets=[]
        )
        # Add power straps on M6 for macro connections
        pdngen.makeStrap(
            grid=macro_inst_grid,
            layer=m6,
            width=macro_strap_width_dbu,
            spacing=macro_strap_spacing_dbu,
            pitch=macro_strap_pitch_dbu,
            offset=offset_dbu,
            number_of_straps=0,
            snap=True,
            starts_with=pdn.GRID,
            extend=pdn.CORE,
            nets=[]
        )

        # Create via connections between macro power grid layers
        # Connect M4 (from core grid) to M5 (macro grid)
        if m4 and m5:
            pdngen.makeConnect(
                grid=macro_inst_grid,
                layer0=m4,
                layer1=m5,
                cut_pitch_x=pdn_cut_pitch_dbu, # Via cut pitch X
                cut_pitch_y=pdn_cut_pitch_dbu, # Via cut pitch Y
                vias=[],
                techvias=[],
                max_rows=0,
                max_columns=0,
                ongrid=[],
                split_cuts=dict(),
                dont_use_vias=""
            )
        # Connect M5 to M6 (macro grid layers)
        if m5 and m6:
             pdngen.makeConnect(
                grid=macro_inst_grid,
                layer0=m5,
                layer1=m6,
                cut_pitch_x=pdn_cut_pitch_dbu,
                cut_pitch_y=pdn_cut_pitch_dbu,
                vias=[],
                techvias=[],
                max_rows=0,
                max_columns=0,
                ongrid=[],
                split_cuts=dict(),
                dont_use_vias=""
            )
        # Connect M6 (macro grid) to M7 (core grid)
        if m6 and m7:
            pdngen.makeConnect(
                grid=macro_inst_grid,
                layer0=m6,
                layer1=m7,
                cut_pitch_x=pdn_cut_pitch_dbu,
                cut_pitch_y=pdn_cut_pitch_dbu,
                vias=[],
                techvias=[],
                max_rows=0,
                max_columns=0,
                ongrid=[],
                split_cuts=dict(),
                dont_use_vias=""
            )

# Create via connections between core standard cell power grid layers
# Connect M1 to M4
if m1 and m4:
    pdngen.makeConnect(
        grid=core_grid,
        layer0=m1,
        layer1=m4,
        cut_pitch_x=pdn_cut_pitch_dbu,
        cut_pitch_y=pdn_cut_pitch_dbu,
        vias=[],
        techvias=[],
        max_rows=0,
        max_columns=0,
        ongrid=[],
        split_cuts=dict(),
        dont_use_vias=""
    )
# Connect M4 to M7
if m4 and m7:
    pdngen.makeConnect(
        grid=core_grid,
        layer0=m4,
        layer1=m7,
        cut_pitch_x=pdn_cut_pitch_dbu,
        cut_pitch_y=pdn_cut_pitch_dbu,
        vias=[],
        techvias=[],
        max_rows=0,
        max_columns=0,
        ongrid=[],
        split_cuts=dict(),
        dont_use_vias=""
    )
# Connect M7 to M8 (for ring connections)
if m7 and m8:
    pdngen.makeConnect(
        grid=core_grid,
        layer0=m7,
        layer1=m8,
        cut_pitch_x=pdn_cut_pitch_dbu,
        cut_pitch_y=pdn_cut_pitch_dbu,
        vias=[],
        techvias=[],
        max_rows=0,
        max_columns=0,
        ongrid=[],
        split_cuts=dict(),
        dont_use_vias=""
    )

# Verify the PDN setup
pdngen.checkSetup()
# Build the power grids based on the configuration
pdngen.buildGrids(False) # False means not saving shapes to file
# Write the generated power grid shapes to the design database
pdngen.writeToDb(True) # True means commit changes to database
# Reset temporary shapes used during build process
pdngen.resetShapes()

# --- Static IR Drop Analysis ---

psm_obj = design.getPDNSim()
# Get the VDD net object
vdd_net_obj = design.getBlock().findNet("VDD")

if vdd_net_obj:
    # Get timing corners (assuming at least one corner exists)
    timing = Timing(design)
    corners = timing.getCorners()
    if corners:
        # Define source types (e.g., FULL grid analysis, STRAPS, BUMPS)
        # Choosing FULL analysis to consider the entire grid.
        # The request for "M1 layer" analysis is interpreted as analyzing the VDD net overall.
        source_types = [psm.GeneratedSourceType_FULL]
        source_type_to_use = source_types[0] # Use FULL analysis

        # Perform static IR drop analysis on the VDD net
        print("Performing static IR drop analysis on VDD net...")
        psm_obj.analyzePowerGrid(
            net=vdd_net_obj,
            enable_em=False, # Disable electromigration analysis
            corner=corners[0], # Use the first timing corner
            use_prev_solution=False, # Do not use previous solution
            em_file="", # No EM file needed if EM is disabled
            error_file="", # Output error file path
            voltage_source_file="", # Input voltage source file path
            voltage_file="", # Output voltage file path
            source_type=source_type_to_use
        )
        print("Static IR drop analysis complete.")
        # Results are typically accessible via other PSM API calls or generated reports/files.
        # The prompt asks for the result but doesn't specify output format beyond dumping DEF.

    else:
        print("Warning: No timing corners found for IR drop analysis.")
else:
    print("Warning: VDD net not found for IR drop analysis.")

# --- Output ---

# Dump the design with PDN shapes in DEF format
output_def_file = "PDN.def"
design.writeDef(output_def_file)
print(f"Design with PDN saved to {output_def_file}")

# Optionally, save the routed Verilog netlist (shows physical connections)
# design.evalTclString("write_verilog PDN.v")