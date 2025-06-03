# Import necessary OpenROAD modules
import odb # Database access
import pdn # Power Delivery Network definition types (e.g., pdn.GRID)
import drt # Detailed Router types (e.g., drt.ParamStruct)
import openroad as ord # Main OpenROAD interface
import sys # To exit on errors

# Assume the netlist is already read and libraries are loaded before this script runs.
# This script operates on the loaded design in the OpenROAD database.
# Access the database and the top-level block (design)
db = ord.get_db()
tech = db.getTech()
block = db.getChip().getBlock()

if not block:
    print("Error: No block loaded in the database. Please load a netlist.", file=sys.stderr)
    sys.exit(1) # Exit with an error code

if not tech:
    print("Error: No technology loaded in the database. Please load libraries.", file=sys.stderr)
    sys.exit(1) # Exit with an error code


print("OpenROAD Python script started.")

# 1. Set the clock period
# Given clock port "clk", period 20 ns
clock_period_ns = 20
clock_port_name = "clk"
clock_net_name = "core_clock" # Naming the clock net
clock_period_ps = clock_period_ns * 1000

# Create and propagate clock. This is typically done via Tcl commands
# or dedicated clock setup functions before placement.
# Using evalTclString is common for setting up clocks early in the flow.
print(f"Setting up clock '{clock_port_name}' with period {clock_period_ns} ns...")
ord.evalTclString(f"create_clock -period {clock_period_ps} [get_ports {clock_port_name}] -name {clock_net_name}")
ord.evalTclString(f"set_propagated_clock [get_clocks {{{clock_net_name}}}]") # Use {{{}}} for list in string


# 2. Perform floorplan
print("Performing floorplan...")
floorplan = ord.get_floorplan()

# Set die bounding box (0,0) to (45,45) um
die_lx_um = 0.0
die_ly_um = 0.0
die_ux_um = 45.0
die_uy_um = 45.0
die_area = odb.Rect(db.micronToDBU(die_lx_um), db.micronToDBU(die_ly_um),
                    db.micronToDBU(die_ux_um), db.micronToDBU(die_uy_um))

# Set core bounding box (5,5) to (40,40) um
core_lx_um = 5.0
core_ly_um = 5.0
core_ux_um = 40.0
core_uy_um = 40.0
core_area = odb.Rect(db.micronToDBU(core_lx_um), db.micronToDBU(core_ly_um),
                     db.micronToDBU(core_ux_um), db.micronToDBU(core_uy_um))

# Find standard cell site definition
# Look for a 'CORE' site type. If not found, fall back to the first site in the tech.
site = None
if tech:
    for site_def in tech.getSites():
        if site_def.getType() == "CORE": # Common type for standard cell sites
             site = site_def
             print(f"Found CORE site: {site.getName()}")
             break
    if not site and tech.getSites():
         site = tech.getSites()[0]
         print(f"Warning: No CORE site found. Using first site found: {site.getName()}", file=sys.stderr)

if not site:
    print("Error: No standard cell site found in the technology library. Cannot perform floorplan.", file=sys.stderr)
    sys.exit(1) # Cannot proceed without a site

# Initialize the floorplan
floorplan.initFloorplan(die_area, core_area, site)

# Generate standard cell tracks (needed for placement)
floorplan.makeTracks()
print("Floorplan complete.")

# 3. Place macros and standard cells
print("Starting placement...")
# Identify macros (instances whose master is a block)
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

# Macro Placement (if macros exist)
if macros:
    print(f"Found {len(macros)} macros. Performing macro placement...")
    mpl = ord.get_macro_placer()

    # Set fence region (5um,5um) to (20um,25um)
    fence_lx_um = 5.0
    fence_ly_um = 5.0
    fence_ux_um = 20.0
    fence_uy_um = 25.0

    # Set halo region around each macro (5um)
    halo_width_um = 5.0
    halo_height_um = 5.0

    # Note: The mpl.place API does not appear to have a direct parameter for minimum macro separation (5um).
    # This constraint might need to be handled by a different macro placement tool, a manual step,
    # or relied upon by the detailed placer to resolve overlaps.
    # We will set the available parameters from the prompt/example.
    # Assuming mpl.place expects micron values for fence coordinates and halo
    mpl.place(
        num_threads = ord.get_threads(), # Use available threads configured in OpenROAD
        halo_width = halo_width_um,
        halo_height = halo_height_um,
        fence_lx = fence_lx_um,
        fence_ly = fence_ly_um,
        fence_ux = fence_ux_um,
        fence_uy = fence_uy_um, # Corrected typo from Gemini draft
        # Other parameters from example (adjust as needed for specific designs)
        max_num_macro = len(macros)//8 if len(macros) > 8 else 1,
        min_num_macro = 0,
        max_num_inst = 0,
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
    print("No macros found. Skipping macro placement.")


# Global Placement (Standard Cells)
print("Performing global placement...")
gpl = ord.get_replace()
gpl.setTimingDrivenMode(False) # Prompt does not specify timing-driven placement
gpl.setRoutabilityDrivenMode(True)
gpl.setUniformTargetDensityMode(True)

# The prompt specified global router iterations, not global placement iterations.
# Removed setInitialPlaceMaxIter found in the Gemini draft.

gpl.doInitialPlace(threads = ord.get_threads())
gpl.doNesterovPlace(threads = ord.get_threads())
gpl.reset() # Reset placer state after running

# Detailed Placement
print("Performing detailed placement...")
opendp = ord.get_opendp()

# Set maximum displacement at the x-axis as 1 um, and the y-axis as 3 um
max_disp_x_um = 1.0
max_disp_y_um = 3.0
# Convert to database units as opendp.detailedPlacement expects DBU
max_disp_x_dbu = db.micronToDBU(max_disp_x_um)
max_disp_y_dbu = db.micronToDBU(max_disp_y_um)

# Remove existing filler cells before detailed placement (good practice)
# This prevents fillers from blocking standard cells during DP.
opendp.removeFillers()

# Perform detailed placement
# Note: opendp.detailedPlacement takes DBU values for max_disp_x/y
# The third argument is cell_type, "" means all movable standard cells.
# The fourth argument is verbose flag.
opendp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

print("Placement complete.")


# 4. Clock Tree Synthesis (CTS)
print("Performing clock tree synthesis...")
cts = ord.get_triton_cts()

# Set unit resistance and unit capacitance value for clock and signal wires
r_per_unit = 0.03574
c_per_unit = 0.07516
# Note: set_wire_rc is typically a Tcl command. Using evalTclString is appropriate.
ord.evalTclString(f"set_wire_rc -clock -resistance {r_per_unit} -capacitance {c_per_unit}")
ord.evalTclString(f"set_wire_rc -signal -resistance {r_per_unit} -capacitance {c_per_unit}")

# Set clock buffers using BUF_X2
cts.setBufferList("BUF_X2") # Specify the list of buffers CTS can use
cts.setRootBuffer("BUF_X2") # Specify the buffer to use at the root node (optional)
cts.setSinkBuffer("BUF_X2") # Specify the buffer to use for sink nodes (optional)

# Configure other CTS parameters if needed (e.g., target skew, max capacitance)
# Example: cts.getParms().setWireSegmentUnit(20) # From Gemini draft, not in prompt.

# Run CTS
cts.runTritonCts()
print("Clock Tree Synthesis complete.")


# 5. Power Delivery Network (PDN) Construction
print("Building Power Delivery Network...")
pdngen = ord.get_pdngen()

# Find or create power/ground nets and mark them as special
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

if VDD_net is None:
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSigType("POWER")
    print("Created VDD net.")
if VSS_net is None:
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSigType("GROUND")
    print("Created VSS net.")

VDD_net.setSpecial()
VSS_net.setSpecial()

# Connect power pins of instances to the global power/ground nets
# This assumes standard pin names like VDD/VSS. Adjust patterns if necessary based on library.
print("Connecting instance power pins to global nets...")
# Example patterns from Gemini draft - adjust based on actual library pin names
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDPE$", net = VDD_net, do_connect = True)
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDCE$", net = VDD_net, do_connect = True)
block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSSE$", net = VSS_net, do_connect = True)
block.globalConnect()
print("Global power pin connection complete.")

# Set the core voltage domain
# Find the Core domain object. If it doesn't exist, setCoreDomain creates it implicitly.
core_domain = pdngen.findDomain("Core")
if core_domain is None:
    print("Creating Core PDN domain.")
    pdngen.setCoreDomain(power = VDD_net, ground = VSS_net) # No switched/secondary mentioned

# Get required metal layers from the technology database
m1 = tech.findLayer("metal1")
m4 = tech.findLayer("metal4")
m5 = tech.findLayer("metal5")
m6 = tech.findLayer("metal6")
m7 = tech.findLayer("metal7")
m8 = tech.findLayer("metal8")

# Check if all required layers were found
required_layers = {'metal1': m1, 'metal4': m4, 'metal5': m5, 'metal6': m6, 'metal7': m7, 'metal8': m8}
missing_layers = [name for name, layer in required_layers.items() if layer is None]
if missing_layers:
    print(f"Error: Could not find required metal layers in technology: {', '.join(missing_layers)}. Cannot build PDN.", file=sys.stderr)
    sys.exit(1) # Cannot proceed without required layers

# Set via cut pitch to 0 um (0 DBU) between parallel grids as specified
# This parameter is used in makeConnect.
via_cut_pitch_dbu = db.micronToDBU(0.0) # Use float for micron value


# Create the main core grid structure (usually covers the core area)
# This grid object will be used to add rings, straps, and connections for standard cells.
core_grid_name = "core_grid"
pdngen.makeCoreGrid(domain = pdngen.findDomain("Core"), name = core_grid_name)

# Get the core grid object(s) - should be one with this name
core_grids = pdngen.findGrid(core_grid_name)

if not core_grids:
     print(f"Error: Core grid '{core_grid_name}' not found after makeCoreGrid. Cannot add straps/rings.", file=sys.stderr)
     # Handle error or exit
else:
    core_grid = core_grids[0] # Assuming a single core grid

    print(f"Adding power structures to '{core_grid_name}'...")

    # Add power rings on M7 and M8 around the core area
    # "power rings on M7 and M8 ... For the power rings on M7, set the width and spacing to 2 and 2 um, and for the power rings on M8, set the width and spacing to 2 and 2 um as well."
    ring_width_um = 2.0
    ring_spacing_um = 2.0
    # "Set the offset to 0 for all cases." Offset from core boundary for rings is 0.
    ring_offset_um = 0.0
    pdngen.makeRing(grid = core_grid,
        layer0 = m7, width0 = db.micronToDBU(ring_width_um), spacing0 = db.micronToDBU(ring_spacing_um),
        layer1 = m8, width1 = db.micronToDBU(ring_width_um), spacing1 = db.micronToDBU(ring_spacing_um),
        starts_with = pdn.GRID, # Pattern based on grid boundary
        offset = [db.micronToDBU(ring_offset_um)] * 4, # [L, B, R, T] offset from core boundary
        nets = []) # Apply to all nets in the grid (VDD/VSS)
    print(f"Added M7/M8 rings (W={ring_width_um}um, S={ring_spacing_um}um) around core.")


    # Add horizontal power straps on metal1 for standard cells (following pins)
    # "have power grids on M1 ... for standard cells respectively. Set the width of the M1 grid as 0.07 um"
    m1_width_um = 0.07
    pdngen.makeFollowpin(grid = core_grid,
        layer = m1,
        width = db.micronToDBU(m1_width_um),
        extend = pdn.CORE) # Extend within the core area
    print(f"Added M1 followpin straps (W={m1_width_um}um) for standard cells.")

    # Add power straps on metal4
    # "have power grids on ... M4 for standard cells and macros respectively. Set the width of the M4 grid is 1.2 um. Set the spacing of the M4 grid as 1.2 um and the pitch of the M4 power grid as 6 um."
    # "Set the offset to 0 for all cases."
    m4_width_um = 1.2
    m4_spacing_um = 1.2
    m4_pitch_um = 6.0
    m4_offset_um = 0.0
    pdngen.makeStrap(grid = core_grid,
        layer = m4,
        width = db.micronToDBU(m4_width_um),
        spacing = db.micronToDBU(m4_spacing_um),
        pitch = db.micronToDBU(m4_pitch_um),
        offset = db.micronToDBU(m4_offset_um),
        starts_with = pdn.GRID,
        extend = pdn.CORE, # Extend across the core area
        nets = [])
    print(f"Added M4 straps (W={m4_width_um}um, S={m4_spacing_um}um, P={m4_pitch_um}um) across core.")

    # Add power straps on metal7
    # "Set the width of the power grids on M7 to 1.4 um and set the spacing and the pitch to 1.4 um and 10.8 um."
    # "Set the offset to 0 for all cases."
    m7_width_um = 1.4
    m7_spacing_um = 1.4
    m7_pitch_um = 10.8
    m7_offset_um = 0.0
    pdngen.makeStrap(grid = core_grid,
        layer = m7,
        width = db.micronToDBU(m7_width_um),
        spacing = db.micronToDBU(m7_spacing_um),
        pitch = db.micronToDBU(m7_pitch_um),
        offset = db.micronToDBU(m7_offset_um),
        starts_with = pdn.GRID,
        extend = pdn.RINGS, # Extend to connect with M7/M8 rings
        nets = [])
    print(f"Added M7 straps (W={m7_width_um}um, S={m7_spacing_um}um, P={m7_pitch_um}um) across core.")

    # Note: M8 straps with M7 parameters were in the Gemini draft but not in the prompt.
    # The prompt only specifies M8 for rings. So, no separate M8 straps are added here.

    # Add via connections between core grid layers
    # "If there are parallel grids, set the pitch of the via between two grids to 0 um."
    # This is handled by setting cut_pitch_x and cut_pitch_y to 0 DBU in makeConnect.
    print("Adding core grid via connections (pitch 0um)...")
    pdngen.makeConnect(grid = core_grid, layer0 = m1, layer1 = m4,
                       cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
    pdngen.makeConnect(grid = core_grid, layer0 = m4, layer1 = m7,
                       cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
    # Connect M7 to M8 (rings)
    pdngen.makeConnect(grid = core_grid, layer0 = m7, layer1 = m8,
                       cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
    print("Core grid via connections complete.")


# Create power grids for macro blocks if they exist, using M5 and M6
# "If the design has macros, build power grids for macros on M5 and M6 , set the width and spacing of both M5 and M6 grids to 1.2 um, and set the pitch to 6 um."
# "Set the offset to 0 for all cases."
if macros:
    print(f"Creating instance grids for {len(macros)} macros using M5/M6...")
    macro_strap_width_um = 1.2
    macro_strap_spacing_um = 1.2
    macro_strap_pitch_um = 6.0
    macro_strap_offset_um = 0.0
    # Halo for macro instance grid exclusion area (using the same 5um halo from placement)
    macro_halo_um = 5.0
    macro_halo_dbu = [db.micronToDBU(macro_halo_um)] * 4 # [L, B, R, T]

    for i, macro_inst in enumerate(macros):
        # Create a separate instance grid for each macro
        instance_grid_name = f"macro_grid_{macro_inst.getName()}" # Use instance name for clarity
        print(f"  Creating instance grid '{instance_grid_name}' for macro '{macro_inst.getName()}'...")
        pdngen.makeInstanceGrid(domain = pdngen.findDomain("Core"), # Associate with Core domain
                                name = instance_grid_name,
                                inst = macro_inst,
                                halo = macro_halo_dbu, # Exclude area around macro for core grid, or define macro grid extent
                                pg_pins_to_boundary = True, # Connect macro PG pins to grid boundary
                                default_grid = False) # This is an instance-specific grid

        # Get the grid created for this macro instance
        instance_grids = pdngen.findGrid(instance_grid_name)
        if not instance_grids:
             print(f"  Error: Instance grid '{instance_grid_name}' not found after creation. Skipping straps/connections.", file=sys.stderr)
             continue # Skip adding straps/connections for this macro

        instance_grid = instance_grids[0] # Assuming a single instance grid per macro

        # Add power straps on metal5 for macro connections
        pdngen.makeStrap(grid = instance_grid,
            layer = m5,
            width = db.micronToDBU(macro_strap_width_um),
            spacing = db.micronToDBU(macro_strap_spacing_um),
            pitch = db.micronToDBU(macro_strap_pitch_um),
            offset = db.micronToDBU(macro_strap_offset_um),
            snap = True, # Gemini had snap=True for instance grids, let's keep it
            starts_with = pdn.GRID, # Pattern based on grid boundary
            extend = pdn.CORE, # Extend within the macro's core area boundary defined by halo
            nets = []) # Apply to all nets in the grid (VDD/VSS)
        print(f"    Added M5 straps (W={macro_strap_width_um}um, S={macro_strap_spacing_um}um, P={macro_strap_pitch_um}um).")

        # Add power straps on metal6 for macro connections
        pdngen.makeStrap(grid = instance_grid,
            layer = m6,
            width = db.micronToDBU(macro_strap_width_um),
            spacing = db.micronToDBU(macro_strap_spacing_um),
            pitch = db.micronToDBU(macro_strap_pitch_um),
            offset = db.micronToDBU(macro_strap_offset_um),
            snap = True, # Gemini had snap=True for instance grids, let's keep it
            starts_with = pdn.GRID, # Pattern based on grid boundary
            extend = pdn.CORE, # Extend within the macro's core area boundary defined by halo
            nets = [])
        print(f"    Added M6 straps (W={macro_strap_width_um}um, S={macro_strap_spacing_um}um, P={macro_strap_pitch_um}um).")

        # Add via connections between macro grid layers and connecting layers
        # "If there are parallel grids, set the pitch of the via between two grids to 0 um."
        print("    Adding instance grid via connections (pitch 0um)...")
        # Connect M4 (core grid) to M5 (macro grid)
        pdngen.makeConnect(grid = instance_grid, layer0 = m4, layer1 = m5,
                           cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
        # Connect M5 to M6 (macro grid layers)
        pdngen.makeConnect(grid = instance_grid, layer0 = m5, layer1 = m6,
                           cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
        # Connect M6 (macro grid) to M7 (core grid/rings)
        pdngen.makeConnect(grid = instance_grid, layer0 = m6, layer1 = m7,
                           cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
        print("    Instance grid via connections complete.")

print("PDN configuration complete. Building grids geometry...")

# Generate the power delivery network geometry based on the configuration
pdngen.checkSetup() # Verify the PDN configuration
# buildGrids(connect_instance_grid_to_core_grid_port) - Setting to False based on Gemini
pdngen.buildGrids(False) # Build the power grid geometry
# writeToDb(create_fills) - Setting to True based on Gemini
pdngen.writeToDb(True) # Write the generated power grid shapes to the design database
pdngen.resetShapes() # Clean up temporary shapes used during generation

print("Power Delivery Network build complete.")


# Insert filler cells into empty spaces after placement/CTS
# This is often done after detailed placement and potentially after CTS to fill gaps.
print("Inserting filler cells...")
filler_masters = []
# Find CORE_SPACER masters in the library
if db.getLibs():
    for lib in db.getLibs():
        if lib.getMasters():
            for master in lib.getMasters():
                if master.getType() == "CORE_SPACER": # Standard cell filler type
                    filler_masters.append(master)

if not filler_masters:
    print("Warning: No CORE_SPACER filler cells found in library. Skipping filler placement.", file=sys.stderr)
else:
    print(f"Found {len(filler_masters)} filler cell masters. Performing filler placement.")
    # Use the opendp object obtained earlier
    opendp.fillerPlacement(filler_masters = filler_masters,
                           prefix = "FILLCELL_", # Prefix for newly created filler instances
                           verbose = False) # Set to True for more detailed output
    print("Filler cell placement complete.")

# 6. Routing Stage
print("Starting routing...")

# Global Routing
grt = ord.get_global_router()

# Route the design from M1 to M7
# Get routing levels for specified metal layers from the technology
min_route_layer = tech.findLayer("metal1")
max_route_layer = tech.findLayer("metal7")

if not min_route_layer or not max_route_layer:
    print("Error: Could not find metal1 or metal7 for routing range. Cannot perform routing.", file=sys.stderr)
    sys.exit(1)

min_route_level = min_route_layer.getRoutingLevel()
max_route_level = max_route_layer.getRoutingLevel()

grt.setMinRoutingLayer(min_route_level)
grt.setMaxRoutingLayer(max_route_level)
# Use the same range for clock nets unless specified otherwise
grt.setMinLayerForClock(min_route_level)
grt.setMaxLayerForClock(max_route_level)

# Set the iteration of the global router as 10 times
grt.setIterations(10)
print(f"Global Router iterations set to {grt.getIterations()}.")

# Set routing adjustment (example from Gemini, not explicitly in prompt, but common)
# grt.setAdjustment(0.5)
# grt.setVerbose(True) # Example from Gemini

# Run global routing
print("Performing global routing...")
grt.globalRoute(True) # True for congestion-aware global routing
print("Global routing complete.")

# Detailed Routing
print("Performing detailed routing...")
drter = ord.get_triton_route()
params = drt.ParamStruct()

# Set detailed routing parameters
# Route the design from M1 to M7
params.bottomRoutingLayer = min_route_layer.getName()
params.topRoutingLayer = max_route_layer.getName()

# Other parameters from Gemini draft - keep standard ones or those implied by flow
params.enableViaGen = True # Enable via generation
params.drouteEndIter = 1 # Number of detailed routing iterations (example: 1)
params.verbose = 0 # Set verbosity (0=quiet, 1=normal, >1=more)
params.cleanPatches = True # Clean up patches after routing
params.doPa = True # Perform post-route optimization (patching)
params.singleStepDR = False # Run DR in multiple steps (preferred for complex designs)
params.minAccessPoints = 1 # Minimum access points for pins
# params.saveGuideUpdates = False # Not a standard parameter name in drt.ParamStruct

# Remove example parameters like output files, dbProcessNode, orSeed, orK, viaInPin layers
# unless they are truly standard or required by a specific tech setup.

# Apply the configured parameters
drter.setParams(params)

# Run detailed routing
drter.main()
print("Detailed routing complete.")

print("OpenROAD Python script finished.")