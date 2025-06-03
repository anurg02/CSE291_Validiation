import odb
import pdn
import drt
import openroad as ord

# Define clock parameters
clock_period = 20.0  # ns
clock_port_name = "clk"
clock_name = "core_clock"

# Create clock signal
# Sets a clock signal on the specified port with a given period
design.evalTclString(f"create_clock -period {clock_period} [get_ports {clock_port_name}] -name {clock_name}")
# Propagate the clock signal throughout the design
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Initialize floorplan
floorplan = design.getFloorplan()

# Define die and core areas in microns
die_lx_micron, die_ly_micron = 0.0, 0.0
die_ux_micron, die_uy_micron = 40.0, 60.0
core_lx_micron, core_ly_micron = 10.0, 10.0
core_ux_micron, core_uy_micron = 30.0, 50.0

# Convert microns to DBU
die_lx_dbu = design.micronToDBU(die_lx_micron)
die_ly_dbu = design.micronToDBU(die_ly_micron)
die_ux_dbu = design.micronToDBU(die_ux_micron)
die_uy_dbu = design.micronToDBU(die_uy_micron)
core_lx_dbu = design.micronToDBU(core_lx_micron)
core_ly_dbu = design.micronToDBU(core_ly_micron)
core_ux_dbu = design.micronToDBU(core_ux_micron)
core_uy_dbu = design.micronToDBU(core_uy_micron)

# Set die area bounding box
die_area = odb.Rect(die_lx_dbu, die_ly_dbu, die_ux_dbu, die_uy_dbu)
# Set core area bounding box
core_area = odb.Rect(core_lx_dbu, core_ly_dbu, core_ux_dbu, core_uy_dbu)

# Find the standard cell site from the loaded libraries
# Assumes at least one library is loaded and contains a CORE site
site = None
for lib in design.getTech().getDB().getLibs():
    for s in lib.getSites():
        if s.getType() == "CORE":
            site = s
            break
    if site:
        break

if not site:
    print("ERROR: No CORE site found in loaded libraries.")
    exit()

# Initialize floorplan with die and core area and site
floorplan.initFloorplan(die_area, core_area, site)
# Create routing tracks based on the technology and floorplan
floorplan.makeTracks()

# Find macros in the design
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

# Perform macro placement if macros are present
if len(macros) > 0:
    print(f"Found {len(macros)} macros. Performing macro placement.")
    mpl = design.getMacroPlacer()
    block = design.getBlock()

    # Define macro fence region in microns
    fence_lx_micron, fence_ly_micron = 15.0, 10.0
    fence_ux_micron, fence_uy_micron = 30.0, 40.0

    # Define macro halo and spacing in microns
    macro_halo_micron = 5.0
    macro_spacing_micron = 5.0 # mpl.place doesn't have a direct min_macro_distance, halo helps

    # Perform macro placement within the fence region
    mpl.place(
        # General settings
        num_threads = 64,
        max_num_macro = len(macros), # Place all macros
        min_num_macro = 0,
        tolerance = 0.1,
        max_num_level = 2,
        coarsening_ratio = 10.0,
        large_net_threshold = 50,
        signature_net_threshold = 50,
        # Macro specific settings
        halo_width = macro_halo_micron,
        halo_height = macro_halo_micron,
        # Fence region
        fence_lx = fence_lx_micron,
        fence_ly = fence_ly_micron,
        fence_ux = fence_ux_micron,
        fence_uy = fence_uy_micron,
        # Weights (example values)
        area_weight = 0.1,
        outline_weight = 100.0,
        wirelength_weight = 100.0,
        guidance_weight = 10.0,
        fence_weight = 10.0,
        boundary_weight = 50.0,
        notch_weight = 10.0,
        macro_blockage_weight = 10.0,
        pin_access_th = 0.0,
        # Density settings
        target_util = 0.4, # Example utilization
        target_dead_space = 0.05,
        min_ar = 0.5,
        # Other
        snap_layer = 0, # Disable snapping or set to appropriate layer level
        bus_planning_flag = False,
        report_directory = ""
    )
else:
    print("No macros found. Skipping macro placement.")


# Configure and run global placement
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Set timing driven mode off for initial run
gpl.setRoutabilityDrivenMode(True) # Set routability driven mode on
gpl.setUniformTargetDensityMode(True) # Use uniform target density
# Limit initial placement iterations as requested (corresponds to initial place stage)
gpl.setInitialPlaceMaxIter(10)
# Perform initial global placement
gpl.doInitialPlace(threads = 4)
# Perform Nesterov-based global placement
gpl.doNesterovPlace(threads = 4)
# Reset placer for subsequent runs (optional)
gpl.reset()


# Run initial detailed placement
opendp = design.getOpendp()
# Define maximum displacement in microns
max_disp_x_micron = 1.0
max_disp_y_micron = 3.0

# Get site dimensions to convert micron displacement to DBU
site_width_dbu = site.getWidth()
site_height_dbu = site.getHeight()

# Convert max displacement to DBU, relative to site grid
max_disp_x_dbu = int(design.micronToDBU(max_disp_x_micron))
max_disp_y_dbu = int(design.micronToDBU(max_disp_y_micron))

# Detailed placement parameters
# Remove filler cells before placement if any exist
opendp.removeFillers()
# Perform detailed placement allowing specified displacement
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)


# Configure and run clock tree synthesis (CTS)
cts = design.getTritonCts()
# Set available buffer list
cts.setBufferList("BUF_X2")
# Set root buffer (used at the clock source)
cts.setRootBuffer("BUF_X2")
# Set sink buffer (used at clock endpoints)
cts.setSinkBuffer("BUF_X2")
# Set RC values for clock nets
design.evalTclString("set_wire_rc -clock -resistance 0.03574 -capacitance 0.07516")
# Set RC values for regular signal nets
design.evalTclString("set_wire_rc -signal -resistance 0.03574 -capacitance 0.07516")
# Run CTS
cts.runTritonCts()

# Run final detailed placement after CTS
# Detailed placement parameters are the same as initial detailed placement
# Remove filler cells again before final detailed placement
opendp.removeFillers()
# Perform detailed placement
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)


# Configure and generate Power Delivery Network (PDN)
pdngen = design.getPdnGen()

# Set up global power/ground connections
# Iterate through nets and mark power/ground nets as special
for net in design.getBlock().getNets():
    if net.getSigType() == "POWER" or net.getSigType() == "GROUND":
        net.setSpecial()

# Find existing power and ground nets or create if needed
# Assumes nets named "VDD" and "VSS" exist or can be created
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")
switched_power = None  # No switched power domain defined
secondary_nets = list() # No secondary power nets defined

# Create VDD/VSS nets if they do not exist in the netlist
if VDD_net is None:
    VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
    VDD_net.setSigType("POWER") # Set signal type to POWER
    VDD_net.setSpecial() # Mark as special net
if VSS_net is None:
    VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
    VSS_net.setSigType("GROUND") # Set signal type to GROUND
    VSS_net.setSpecial() # Mark as special net

# Connect power pins of standard cells to global nets
# Connect VDD pins to VDD_net
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
# Connect VSS pins to VSS_net
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
# Apply the global connections
design.getBlock().globalConnect()


# Configure the core power domain
pdngen.setCoreDomain(power = VDD_net, switched_power = switched_power, ground = VSS_net, secondary = secondary_nets)
domains = [pdngen.findDomain("Core")]

# Set via cut pitch for connections between parallel grid layers
# Pitch is set to 0 um as requested
pdn_cut_pitch_x_dbu = design.micronToDBU(0)
pdn_cut_pitch_y_dbu = design.micronToDBU(0)

# Get required metal layers
m1 = design.getTech().getDB().getTech().findLayer("metal1")
m4 = design.getTech().getDB().getTech().findLayer("metal4")
m5 = design.getTech().getDB().getTech().findLayer("metal5")
m6 = design.getTech().getDB().getTech().findLayer("metal6")
m7 = design.getTech().getDB().getTech().findLayer("metal7")
m8 = design.getTech().getDB().getTech().findLayer("metal8")

# Check if layers exist
if not all([m1, m4, m5, m6, m7, m8]):
    print("ERROR: One or more specified metal layers not found.")
    exit()

# Create the main core power grid structure
for domain in domains:
    pdngen.makeCoreGrid(domain = domain,
        name = "core_stdcell_grid",
        starts_with = pdn.GROUND, # Start grid pattern with ground net
        pin_layers = [],
        generate_obstructions = [],
        powercell = None,
        powercontrol = None,
        powercontrolnetwork = "STAR") # Use STAR network type (common)

# Get the core grid object
core_grid = pdngen.findGrid("core_stdcell_grid")[0]

# Create standard cell power grid structures
# M1 followpin straps (following standard cell pin pattern)
pdngen.makeFollowpin(grid = core_grid,
    layer = m1,
    width = design.micronToDBU(0.07), # 0.07um width
    extend = pdn.CORE) # Extend within the core area

# M4 straps
pdngen.makeStrap(grid = core_grid,
    layer = m4,
    width = design.micronToDBU(1.2), # 1.2um width
    spacing = design.micronToDBU(1.2), # 1.2um spacing
    pitch = design.micronToDBU(6), # 6um pitch
    offset = design.micronToDBU(0), # 0um offset
    number_of_straps = 0, # Auto-calculate number of straps
    snap = False, # Do not snap to grid
    starts_with = pdn.GRID, # Pattern starts based on grid definition
    extend = pdn.CORE, # Extend within core
    nets = [])

# M7 straps
pdngen.makeStrap(grid = core_grid,
    layer = m7,
    width = design.micronToDBU(1.4), # 1.4um width
    spacing = design.micronToDBU(1.4), # 1.4um spacing
    pitch = design.micronToDBU(10.8), # 10.8um pitch
    offset = design.micronToDBU(0), # 0um offset
    number_of_straps = 0,
    snap = False,
    starts_with = pdn.GRID,
    extend = pdn.CORE,
    nets = [])


# Create power rings around the core area
# M7 ring
pdngen.makeRing(grid = core_grid,
    layer0 = m7,
    width0 = design.micronToDBU(2.0), # 2um width
    spacing0 = design.micronToDBU(2.0), # 2um spacing
    layer1 = None, # Single layer ring definition
    width1 = 0,
    spacing1 = 0,
    starts_with = pdn.GRID, # Pattern starts based on grid
    offset = [design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0)], # 0um offset from core boundary
    pad_offset = [design.micronToDBU(0), design.micronToDBU(0)], # 0um pad offset
    extend = False, # Do not extend beyond core
    pad_pin_layers = [],
    nets = [])

# M8 ring
pdngen.makeRing(grid = core_grid,
    layer0 = m8,
    width0 = design.micronToDBU(2.0), # 2um width
    spacing0 = design.micronToDBU(2.0), # 2um spacing
    layer1 = None,
    width1 = 0,
    spacing1 = 0,
    starts_with = pdn.GRID,
    offset = [design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0), design.micronToDBU(0)], # 0um offset
    pad_offset = [design.micronToDBU(0), design.micronToDBU(0)], # 0um pad offset
    extend = False,
    pad_pin_layers = [],
    nets = [])


# Create power grids for macro blocks if they exist
if len(macros) > 0:
    print("Configuring PDN for macros.")
    macro_halo_dbu = design.micronToDBU(macro_halo_micron)
    halo = [macro_halo_dbu for _ in range(4)] # Use macro halo as keepout for standard cell PDN

    for i, macro_inst in enumerate(macros):
        # Create a specific instance grid for each macro
        for domain in domains:
            pdngen.makeInstanceGrid(domain = domain,
                name = f"macro_grid_{i}",
                starts_with = pdn.GROUND, # Start pattern with ground
                inst = macro_inst, # Assign to this specific macro instance
                halo = halo, # Halo around macro to exclude core grid
                pg_pins_to_boundary = True, # Connect macro PG pins to this grid boundary
                default_grid = False,
                generate_obstructions = [],
                is_bump = False)

        macro_instance_grid = pdngen.findGrid(f"macro_grid_{i}")[0]

        # Add M5 straps for macros
        pdngen.makeStrap(grid = macro_instance_grid,
            layer = m5,
            width = design.micronToDBU(1.2), # 1.2um width
            spacing = design.micronToDBU(1.2), # 1.2um spacing
            pitch = design.micronToDBU(6), # 6um pitch
            offset = design.micronToDBU(0), # 0um offset
            number_of_straps = 0,
            snap = True, # Snap to grid
            starts_with = pdn.GRID,
            extend = pdn.CORE, # Extend within macro core (or instance boundary)
            nets = [])

        # Add M6 straps for macros
        pdngen.makeStrap(grid = macro_instance_grid,
            layer = m6,
            width = design.micronToDBU(1.2), # 1.2um width
            spacing = design.micronToDBU(1.2), # 1.2um spacing
            pitch = design.micronToDBU(6), # 6um pitch
            offset = design.micronToDBU(0), # 0um offset
            number_of_straps = 0,
            snap = True,
            starts_with = pdn.GRID,
            extend = pdn.CORE,
            nets = [])

        # Create via connections for macro grid layers
        # M4 (core grid) to M5 (macro grid)
        pdngen.makeConnect(grid = macro_instance_grid,
            layer0 = m4,
            layer1 = m5,
            cut_pitch_x = pdn_cut_pitch_x_dbu, # Via pitch 0um
            cut_pitch_y = pdn_cut_pitch_y_dbu, # Via pitch 0um
            vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
        # M5 to M6 (macro grid layers)
        pdngen.makeConnect(grid = macro_instance_grid,
            layer0 = m5,
            layer1 = m6,
            cut_pitch_x = pdn_cut_pitch_x_dbu, # Via pitch 0um
            cut_pitch_y = pdn_cut_pitch_y_dbu, # Via pitch 0um
            vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
        # M6 (macro grid) to M7 (core grid)
        pdngen.makeConnect(grid = macro_instance_grid,
            layer0 = m6,
            layer1 = m7,
            cut_pitch_x = pdn_cut_pitch_x_dbu, # Via pitch 0um
            cut_pitch_y = pdn_cut_pitch_y_dbu, # Via pitch 0um
            vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")


# Create via connections for standard cell core grid layers
# M1 to M4
pdngen.makeConnect(grid = core_grid,
    layer0 = m1,
    layer1 = m4,
    cut_pitch_x = pdn_cut_pitch_x_dbu, # Via pitch 0um
    cut_pitch_y = pdn_cut_pitch_y_dbu, # Via pitch 0um
    vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
# M4 to M7
pdngen.makeConnect(grid = core_grid,
    layer0 = m4,
    layer1 = m7,
    cut_pitch_x = pdn_cut_pitch_x_dbu, # Via pitch 0um
    cut_pitch_y = pdn_cut_pitch_y_dbu, # Via pitch 0um
    vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
# M7 to M8
pdngen.makeConnect(grid = core_grid,
    layer0 = m7,
    layer1 = m8,
    cut_pitch_x = pdn_cut_pitch_x_dbu, # Via pitch 0um
    cut_pitch_y = pdn_cut_pitch_y_dbu, # Via pitch 0um
    vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")

# Build the power grids and rings
pdngen.checkSetup() # Verify the PDN setup configuration
pdngen.buildGrids(False) # Generate the PDN shapes
pdngen.writeToDb(True, ) # Write the generated shapes to the design database
pdngen.resetShapes() # Clear internal temporary shapes


# Perform IR Drop Analysis
irdrop = design.getIRDrop()
# Configure IR drop analysis parameters
ir_params = ord.IRDrop.IRDropParams()
# Specify power and ground nets for analysis
ir_params.power_net_names = ["VDD"]
ir_params.ground_net_names = ["VSS"]
# Specify the layer for analysis
ir_params.layer_names = ["metal1"]
# Set voltage units (optional)
ir_params.voltage_units = "Volt"
# Set grid resolution (optional, adjust as needed for detail vs performance)
ir_params.voltage_grid_resolution_x = 1.0 # microns
ir_params.voltage_grid_resolution_y = 1.0 # microns
# Perform the analysis
print("Performing IR drop analysis on metal1...")
irdrop.analyze(ir_params)
print("IR drop analysis complete.")

# Dump the DEF file including the generated PDN
design.writeDef("PDN.def")