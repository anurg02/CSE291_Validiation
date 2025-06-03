import odb
import pdn
import openroad as ord

# --- Configuration Variables ---
tech_file = "tech.tf"  # Placeholder for technology file
liberty_files = ["liberty/ Nangate45/Nangate45.lib"]  # Placeholder for liberty files
lef_files = ["lef/Nangate45/Nangate45.lef"]  # Placeholder for LEF files
verilog_netlist = "netlist.v"  # Placeholder for Verilog netlist
clock_port_name = "clk"
clock_period_ns = 50
site_name = "FreePDK45_38x28_10R_NP_162NW_34O" # Placeholder for site name

# --- 1. Initialization ---
# Read technology file
design.readTech(tech_file)
# Read LEF files
for lef in lef_files:
    design.readLef(lef)
# Read Liberty files
for lib in liberty_files:
    design.readLiberty(lib)
# Read Verilog netlist
design.readVerilog(verilog_netlist)
# Link design
design.linkDesign()

# Dump initial DEF
design.writeDef("initial.def")

# --- 2. Clock Definition ---
# Create clock signal on the specified port
clock_period_ps = clock_period_ns * 1000
design.evalTclString(f"create_clock -period {clock_period_ps} [get_ports {clock_port_name}] -name core_clock")
# Propagate the clock signal
design.evalTclString("set_propagated_clock [all_clocks]")

# --- 3. Floorplanning ---
# Initialize floorplan with core and die area
floorplan = design.getFloorplan()

# Set die area (0,0) to (45,45) um
die_lx = design.micronToDBU(0)
die_ly = design.micronToDBU(0)
die_ux = design.micronToDBU(45)
die_uy = design.micronToDBU(45)
die_area = odb.Rect(die_lx, die_ly, die_ux, die_uy)

# Set core area (5,5) to (40,40) um
core_lx = design.micronToDBU(5)
core_ly = design.micronToDBU(5)
core_ux = design.micronToDBU(40)
core_uy = design.micronToDBU(40)
core_area = odb.Rect(core_lx, core_ly, core_ux, core_uy)

# Find site from the technology library
site = floorplan.findSite(site_name) 
# Initialize floorplan with defined areas and site
floorplan.initFloorplan(die_area, core_area, site)
# Create placement tracks
floorplan.makeTracks()

# Dump floorplan DEF
design.writeDef("floorplan.def")

# --- 4. Placement ---
# Identify macro blocks if present
macros = [inst for inst in design.getBlock().getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    # Configure and run macro placement
    mpl = design.getMacroPlacer()
    block = design.getBlock()
    
    # Set fence region for macros (5,5) to (20,25) um
    fence_lx_micron = 5.0
    fence_ly_micron = 5.0
    fence_ux_micron = 20.0
    fence_uy_micron = 25.0
    mpl.setFenceRegion(fence_lx_micron, fence_ly_micron, fence_ux_micron, fence_uy_micron)
    
    # Set halo region around each macro (5 um)
    halo_width_micron = 5.0
    halo_height_micron = 5.0

    # Run macro placement
    mpl.place(
        num_threads = 64, 
        max_num_macro = len(macros), # Place all macros
        min_num_macro = 0,
        max_num_inst = 0,
        min_num_inst = 0,
        tolerance = 0.1,
        max_num_level = 2,
        coarsening_ratio = 10.0,
        large_net_threshold = 50,
        signature_net_threshold = 50,
        halo_width = halo_width_micron,
        halo_height = halo_height_micron,
        fence_lx = fence_lx_micron,
        fence_ly = fence_ly_micron,
        fence_ux = fence_ux_micron,
        fence_uy = fence_uy_micron,
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
        snap_layer = 4, # Assuming metal4 for snapping
        bus_planning_flag = False,
        report_directory = ""
    )

# Configure and run global placement
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Example setting, timing could be enabled
gpl.setRoutabilityDrivenMode(True) # Example setting
gpl.setUniformTargetDensityMode(True) # Example setting

# Limit initial placement iterations (prompt specified 10 for global, let's apply to initial)
gpl.setInitialPlaceMaxIter(10) 
# Set initial density penalty (example value)
gpl.setInitDensityPenalityFactor(0.05)
# Run initial placement
gpl.doInitialPlace(threads = 4) # Example setting
# Run Nesterov-accelerated placement
gpl.doNesterovPlace(threads = 4) # Example setting
gpl.reset() # Reset placer state

# Run initial detailed placement
site = design.getBlock().getRows()[0].getSite()
# Set max displacement (1um x, 3um y)
max_disp_x_um = 1.0
max_disp_y_um = 3.0
# Convert microns to DBU
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

# Remove filler cells before placement if they exist
design.getOpendp().removeFillers()
# Perform detailed placement
design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False) # Last arg is allow_pin_swap

# Dump placement DEF
design.writeDef("placement.def")

# --- 5. Clock Tree Synthesis (CTS) ---
# Set RC values for clock and signal nets
unit_resistance = 0.03574
unit_capacitance = 0.07516
design.evalTclString(f"set_wire_rc -clock -resistance {unit_resistance} -capacitance {unit_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {unit_resistance} -capacitance {unit_capacitance}")

cts = design.getTritonCts()
parms = cts.getParms()
parms.setWireSegmentUnit(20) # Example setting

# Configure clock buffers
cts.setBufferList("BUF_X2")
cts.setRootBuffer("BUF_X2")
cts.setSinkBuffer("BUF_X2")

# Set the clock net for CTS (using the clock name created earlier)
cts.setClockNets("core_clock")

# Run CTS
cts.runTritonCts()

# Dump DEF after CTS
design.writeDef("cts.def")

# --- 6. Detailed Placement (Post-CTS) ---
# Perform detailed placement again after CTS
# Using the same max displacement limits
site = design.getBlock().getRows()[0].getSite()
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

# Remove filler cells to be able to move cells during detailed placement
design.getOpendp().removeFillers()
# Perform detailed placement
design.getOpendp().detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

# Dump DEF after post-CTS detailed placement
design.writeDef("post_cts_detailed_placement.def")


# --- 7. Power Delivery Network (PDN) ---
# Configure power delivery network
pdngen = design.getPdnGen()

# Set up global power/ground connections
# Mark power/ground nets as special
for net in design.getBlock().getNets():
    if net.getSigType() == "POWER" or net.getSigType() == "GROUND":
        net.setSpecial()

# Find existing power and ground nets or create if needed
VDD_net = design.getBlock().findNet("VDD")
VSS_net = design.getBlock().findNet("VSS")
switched_power = None  # No switched power domain in this design
secondary = list()  # No secondary power nets

# Create VDD/VSS nets if they don't exist
if VDD_net == None:
    VDD_net = odb.dbNet_create(design.getBlock(), "VDD")
    VDD_net.setSpecial()
    VDD_net.setSigType("POWER") # Set signal type to POWER
if VSS_net == None:
    VSS_net = odb.dbNet_create(design.getBlock(), "VSS")
    VSS_net.setSpecial()
    VSS_net.setSigType("GROUND") # Set signal type to GROUND

# Connect power pins to global nets (example uses broad patterns, adjust as needed)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD.*", net = VDD_net, do_connect = True)
design.getBlock().addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS.*", net = VSS_net, do_connect = True)
# Apply the global connections
design.getBlock().globalConnect()

# Set core power domain with primary power/ground nets
pdngen.setCoreDomain(power = VDD_net,
    switched_power = switched_power, 
    ground = VSS_net,
    secondary = secondary)

domains = [pdngen.findDomain("Core")]

# Get metal layers for PDN
tech = design.getTech().getDB().getTech()
m1 = tech.findLayer("metal1")
m4 = tech.findLayer("metal4")
m5 = tech.findLayer("metal5")
m6 = tech.findLayer("metal6")
m7 = tech.findLayer("metal7")
m8 = tech.findLayer("metal8")

# Define dimension parameters in DBU
stdcell_m1_width = design.micronToDBU(0.07)

stdcell_m4_width = design.micronToDBU(1.2)
stdcell_m4_spacing = design.micronToDBU(1.2)
stdcell_m4_pitch = design.micronToDBU(6)

stdcell_m7_strap_width = design.micronToDBU(1.4)
stdcell_m7_strap_spacing = design.micronToDBU(1.4)
stdcell_m7_strap_pitch = design.micronToDBU(10.8)

stdcell_m8_strap_width = design.micronToDBU(1.4)
stdcell_m8_strap_spacing = design.micronToDBU(1.4)
stdcell_m8_strap_pitch = design.micronToDBU(10.8)

stdcell_m7_ring_width = design.micronToDBU(4)
stdcell_m7_ring_spacing = design.micronToDBU(4)

stdcell_m8_ring_width = design.micronToDBU(4)
stdcell_m8_ring_spacing = design.micronToDBU(4)

macro_m5_width = design.micronToDBU(1.2)
macro_m5_spacing = design.micronToDBU(1.2)
macro_m5_pitch = design.micronToDBU(6)

macro_m6_width = design.micronToDBU(1.2)
macro_m6_spacing = design.micronToDBU(1.2)
macro_m6_pitch = design.micronToDBU(6)

macro_m5_ring_width = design.micronToDBU(1.5)
macro_m5_ring_spacing = design.micronToDBU(1.5)

macro_m6_ring_width = design.micronToDBU(1.5)
macro_m6_ring_spacing = design.micronToDBU(1.5)

offset_zero = [design.micronToDBU(0) for i in range(4)]
cut_pitch_zero = [design.micronToDBU(0) for i in range(2)]

# Create power grid for standard cells
for domain in domains:
    # Create the main core grid structure
    pdngen.makeCoreGrid(domain = domain,
    name = "stdcell_core_grid",
    starts_with = pdn.GROUND, # Start with ground net
    pin_layers = [], # No specific pin layers for core grid definition
    generate_obstructions = [],
    powercell = None,
    powercontrol = None,
    powercontrolnetwork = "STAR") # Example setting

core_grid = pdngen.findGrid("stdcell_core_grid")
for g in core_grid:
    # Create power rings around core area using metal7 and metal8
    pdngen.makeRing(grid = g,
        layer0 = m7,
        width0 = stdcell_m7_ring_width,
        spacing0 = stdcell_m7_ring_spacing,
        layer1 = m8,
        width1 = stdcell_m8_ring_width,
        spacing1 = stdcell_m8_ring_spacing,
        starts_with = pdn.GRID,
        offset = offset_zero, # Offset to 0
        pad_offset = offset_zero, # Pad offset to 0
        extend = False, # Do not extend rings
        pad_pin_layers = [], # No specific pad pin layers mentioned
        nets = [])
  
    # Create horizontal power straps on metal1 following standard cell power rails
    pdngen.makeFollowpin(grid = g,
        layer = m1, 
        width = stdcell_m1_width,
        extend = pdn.CORE) # Extend within the core area
  
    # Create vertical power straps on metal4
    pdngen.makeStrap(grid = g,
        layer = m4,
        width = stdcell_m4_width,
        spacing = stdcell_m4_spacing,
        pitch = stdcell_m4_pitch,
        offset = design.micronToDBU(0), # Offset to 0
        number_of_straps = 0,  # Auto-calculate number of straps
        snap = False,
        starts_with = pdn.GRID,
        extend = pdn.CORE, # Extend within the core area
        nets = [])
    
    # Create horizontal power straps on metal7
    pdngen.makeStrap(grid = g,
        layer = m7,
        width = stdcell_m7_strap_width,
        spacing = stdcell_m7_strap_spacing,
        pitch = stdcell_m7_strap_pitch,
        offset = design.micronToDBU(0), # Offset to 0
        number_of_straps = 0,
        snap = False,
        starts_with = pdn.GRID,
        extend = pdn.CORE, # Extend within the core area
        nets = [])

    # Create vertical power straps on metal8
    pdngen.makeStrap(grid = g,
        layer = m8,
        width = stdcell_m8_strap_width,
        spacing = stdcell_m8_strap_spacing,
        pitch = stdcell_m8_strap_pitch,
        offset = design.micronToDBU(0), # Offset to 0
        number_of_straps = 0,
        snap = False,
        starts_with = pdn.GRID,
        extend = pdn.CORE, # Extend within the core area
        nets = [])
  
    # Create via connections between standard cell power grid layers
    # Connect metal1 to metal4
    pdngen.makeConnect(grid = g,
        layer0 = m1,
        layer1 = m4, 
        cut_pitch_x = cut_pitch_zero[0],
        cut_pitch_y = cut_pitch_zero[1],
        vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
    # Connect metal4 to metal7
    pdngen.makeConnect(grid = g,
        layer0 = m4,
        layer1 = m7,
        cut_pitch_x = cut_pitch_zero[0],
        cut_pitch_y = cut_pitch_zero[1],
        vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
    # Connect metal7 to metal8
    pdngen.makeConnect(grid = g,
        layer0 = m7,
        layer1 = m8,
        cut_pitch_x = cut_pitch_zero[0],
        cut_pitch_y = cut_pitch_zero[1],
        vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")


# Create power grid for macro blocks if macros exist
if len(macros) > 0:
    # Halo setting for macro power grid generation
    macro_halo_um = 5.0
    macro_halo_dbu = [design.micronToDBU(macro_halo_um) for i in range(4)]

    for i, macro_inst in enumerate(macros):
        # Create separate power grid for each macro instance
        for domain in domains:
            pdngen.makeInstanceGrid(domain = domain,
                name = f"macro_grid_{macro_inst.getName()}", # Unique name per macro
                starts_with = pdn.GROUND,
                inst = macro_inst,
                halo = macro_halo_dbu, # Halo around the macro
                pg_pins_to_boundary = True,  # Connect power/ground pins to boundary
                default_grid = False, 
                generate_obstructions = [],
                is_bump = False)
        
        # Find the newly created macro grid
        macro_grids = pdngen.findGrid(f"macro_grid_{macro_inst.getName()}")
        for mg in macro_grids:
            # Create power ring around macro using metal5 and metal6
            pdngen.makeRing(grid = mg, 
                layer0 = m5, 
                width0 = macro_m5_ring_width, 
                spacing0 = macro_m5_ring_spacing,
                layer1 = m6, 
                width1 = macro_m6_ring_width, 
                spacing1 = macro_m6_ring_spacing,
                starts_with = pdn.GRID, 
                offset = offset_zero, # Offset to 0
                pad_offset = offset_zero, # Pad offset to 0
                extend = False, # Do not extend rings
                pad_pin_layers = [], # No specific pad pin layers mentioned
                nets = [])
            
            # Create power straps on metal5 for macro connections
            pdngen.makeStrap(grid = mg,
                layer = m5,
                width = macro_m5_width, 
                spacing = macro_m5_spacing,
                pitch = macro_m5_pitch,
                offset = design.micronToDBU(0), # Offset to 0
                number_of_straps = 0,
                snap = True, # Snap straps to grid
                starts_with = pdn.GRID,
                extend = pdn.CORE, # Extend within the macro core area
                nets = [])
            # Create power straps on metal6 for macro connections
            pdngen.makeStrap(grid = mg,
                layer = m6,
                width = macro_m6_width,
                spacing = macro_m6_spacing,
                pitch = macro_m6_pitch,
                offset = design.micronToDBU(0), # Offset to 0
                number_of_straps = 0,
                snap = True, # Snap straps to grid
                starts_with = pdn.GRID,
                extend = pdn.CORE, # Extend within the macro core area
                nets = [])
        
            # Create via connections between macro power grid layers and core grid layers
            # Connect metal4 (from core grid) to metal5 (macro grid)
            pdngen.makeConnect(grid = mg, # Use macro grid handle
                layer0 = m4, # Core grid layer
                layer1 = m5, # Macro grid layer
                cut_pitch_x = cut_pitch_zero[0],
                cut_pitch_y = cut_pitch_zero[1],
                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
            # Connect metal5 to metal6 (macro grid layers)
            pdngen.makeConnect(grid = mg, # Use macro grid handle
                layer0 = m5,
                layer1 = m6,
                cut_pitch_x = cut_pitch_zero[0],
                cut_pitch_y = cut_pitch_zero[1],
                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")
            # Connect metal6 (macro grid) to metal7 (core grid)
            pdngen.makeConnect(grid = mg, # Use macro grid handle
                layer0 = m6, # Macro grid layer
                layer1 = m7, # Core grid layer
                cut_pitch_x = cut_pitch_zero[0],
                cut_pitch_y = cut_pitch_zero[1],
                vias = [], techvias = [], max_rows = 0, max_columns = 0, ongrid = [], split_cuts = dict(), dont_use_vias = "")

# Verify PDN configuration
pdngen.checkSetup()
# Build the power grid shapes
pdngen.buildGrids(False) # trim = False as per example
# Write power grid to the design database
pdngen.writeToDb(True, "") # add_pins = True, no report file
# Reset temporary shapes
pdngen.resetShapes()

# Dump DEF after PDN
design.writeDef("pdn.def")

# --- 8. Filler Insertion ---
db = ord.get_db()
filler_masters = list()
# Find filler cell masters in the library (assuming CORE_SPACER type)
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

if len(filler_masters) == 0:
    print("Warning: No filler cells found in library!")
else:
    # Insert filler cells in empty spaces
    design.getOpendp().fillerPlacement(filler_masters = filler_masters, 
                                     prefix = "filler_", # Prefix for inserted filler instances
                                     verbose = False)

# Dump DEF after filler insertion
design.writeDef("filler.def")

# --- 9. Global Routing ---
# Set routing layer ranges for signal and clock nets (using M1 to M7 as in example)
tech = design.getTech().getDB().getTech()
signal_low_layer = tech.findLayer("metal1").getRoutingLevel()
signal_high_layer = tech.findLayer("metal7").getRoutingLevel()
clk_low_layer = tech.findLayer("metal1").getRoutingLevel()
clk_high_layer = tech.findLayer("metal7").getRoutingLevel()

grt = design.getGlobalRouter()
grt.setMinRoutingLayer(signal_low_layer)
grt.setMaxRoutingLayer(signal_high_layer)
grt.setMinLayerForClock(clk_low_layer)
grt.setMaxLayerForClock(clk_high_layer)
grt.setAdjustment(0.5) # Example setting
grt.setVerbose(True) # Example setting

# Run global routing
# The Python API does not expose an explicit iteration count parameter for globalRoute
# It likely runs a fixed number of iterations internally or until convergence.
# Running with `True` as in the example.
grt.globalRoute(True) # True likely enables some convergence check or default iterations

# Dump DEF after Global Routing
design.writeDef("global_routing.def")

# --- 10. Final Outputs ---
# Write final Verilog netlist
design.evalTclString("write_verilog final.v")

# Write final ODB database file
design.writeDb("final.odb")