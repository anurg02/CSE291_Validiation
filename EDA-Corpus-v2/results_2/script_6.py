import odb
import pdn
import drt
import psm  # Import the psm module for IR drop analysis
import openroad as ord

# Get the current design object
# Assumes a design (netlist, libraries) is already loaded
design = ord.get_main_window().getDesign()
block = design.getBlock()
tech = design.getTech()
db = tech.getDB()

# Set clock signal
# Create clock signal at the clk_i port with a period of 20 ns and name it core_clock
# Using evalTclString as it's a common way to perform standard setup tasks
print("Setting clock signal...")
design.evalTclString("create_clock -period 20 [get_ports clk_i] -name core_clock")
# Propagate the clock signal throughout the design
design.evalTclString("set_propagated_clock [get_clocks {core_clock}]")
print("Clock signal setup complete.")

# Floorplanning
print("Starting floorplanning...")
floorplan = design.getFloorplan()

# Target utilization is 45%
target_utilization = 0.45
# Core to die spacing is 14 microns
spacing_microns = 14.0
spacing_dbu = design.micronToDBU(spacing_microns)

# Get site dimensions for floorplan initialization
# Need to ensure the design has rows before accessing the first site
rows = block.getRows()
if not rows:
    print("Error: No rows found in the design. Cannot initialize floorplan.")
    # Handle the error, e.g., exit or raise exception
    exit(1) # Example error handling
site = rows[0].getSite()

if site is None:
     print("Error: Could not find a site in the design rows. Cannot initialize floorplan.")
     exit(1) # Example error handling

# Initialize floorplan with target utilization, aspect ratio, core-to-die spacing on all sides, and site
# Corrected call based on verification feedback
# API: initFloorplan(utilization, aspect_ratio, core_space_bottom, core_space_top, core_space_left, core_space_right, site)
aspect_ratio = 1.0 # Set aspect ratio to 1.0 as requested
core_space_bottom = spacing_dbu
core_space_top = spacing_dbu
core_space_left = spacing_dbu
core_space_right = spacing_dbu

print(f"Initializing floorplan with utilization {target_utilization}, aspect ratio {aspect_ratio}, and core-to-die spacing {spacing_microns} um on all sides")
floorplan.initFloorplan(target_utilization, aspect_ratio, core_space_bottom, core_space_top, core_space_left, core_space_right, site)
print(f"Core Area: {block.getCoreArea().xMin()},{block.getCoreArea().yMin()} {block.getCoreArea().xMax()},{block.getCoreArea().yMax()}")
print(f"Die Area: {block.getDieArea().xMin()},{block.getDieArea().yMin()} {block.getDieArea().xMax()},{block.getDieArea().yMax()}")

# Create placement tracks based on the floorplan
floorplan.makeTracks()
print("Floorplanning complete.")

# Configure and run I/O pin placement
print("Performing I/O pin placement...")
iop = design.getIOPlacer()
# Get metal layers for pin placement (M8 horizontal, M9 vertical)
m8_layer = db.getTech().findLayer("metal8")
m9_layer = db.getTech().findLayer("metal9")

if m8_layer is None or m9_layer is None:
    print("Error: metal8 or metal9 layer not found for pin placement. Skipping I/O placement.")
else:
    # Clear any previously added layers just in case
    iop.clearHorLayers()
    iop.clearVerLayers()
    iop.addHorLayer(m8_layer)
    iop.addVerLayer(m9_layer)
    # Run I/O placement (using annealing mode for better results)
    # Default parameters like min_distance, corner_avoidance etc. are used if not set
    iop.runAnnealing(True)
    print("I/O pin placement complete.")

# Place macro blocks if present
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]
if len(macros) > 0:
    print(f"Found {len(macros)} macros. Performing macro placement...")
    mpl = design.getMacroPlacer()
    core = block.getCoreArea()

    # Set halo around macros (5 um) - This helps with standard cell placement and routing clearance
    macro_halo_microns = 5.0
    macro_halo_dbu = design.micronToDBU(macro_halo_microns)
    print(f"Setting {macro_halo_microns} um halo around macros.")

    # Define fence to keep macros within the core area
    # Convert core area coordinates to microns for macro placer API
    fence_lx_microns = block.dbuToMicrons(core.xMin())
    fence_ly_microns = block.dbuToMicrons(core.yMin())
    fence_ux_microns = block.dbuToMicrons(core.xMax())
    fence_uy_microns = block.dbuToMicrons(core.yMax())

    # Run macro placement
    mpl.place(
        num_threads = 64, # Use a reasonable number of threads
        max_num_macro = len(macros), # Allow all macros to be placed
        halo_width = macro_halo_microns,
        halo_height = macro_halo_microns,
        fence_lx = fence_lx_microns,
        fence_ly = fence_ly_microns,
        fence_ux = fence_ux_microns,
        fence_uy = fence_uy_microns,
        # Other parameters can be tuned, using defaults for simplicity
        # area_weight = 0.1, outline_weight = 100.0, wirelength_weight = 100.0,
        # guidance_weight = 10.0, fence_weight = 10.0, boundary_weight = 50.0,
        # notch_weight = 10.0, macro_blockage_weight = 10.0, pin_access_th = 0.0,
        target_util = target_utilization, # Pass target utilization
        target_dead_space = 1.0 - target_utilization, # Corresponds to target utilization
        min_ar = 0.33, # Default or reasonable AR
        snap_layer = 1, # Snap to M1 track by default
        bus_planning_flag = False, # Disable bus planning
        report_directory = "" # No report directory
    )
    print("Macro placement complete.")
else:
    print("No macros found. Skipping macro placement.")


# Configure and run standard cell global placement
print("Performing standard cell global placement...")
gpl = design.getReplace()
gpl.setTimingDrivenMode(False) # Not timing driven yet
gpl.setRoutabilityDrivenMode(True)
gpl.setUniformTargetDensityMode(True)
gpl.setTargetDensity(target_utilization) # Set target utilization for global placement

# Run initial placement and Nesterov placement
gpl.doInitialPlace(threads = 4) # Use a reasonable number of threads
gpl.doNesterovPlace(threads = 4) # Use a reasonable number of threads
print("Standard cell global placement complete.")
gpl.reset() # Reset placer state after global placement

# Run initial detailed placement (Pre-CTS)
print("Performing initial detailed placement (Pre-CTS)...")
# Allow 0.5um x-displacement and 1um y-displacement
max_disp_x_microns = 0.5
max_disp_y_microns = 1.0
max_disp_x_dbu = design.micronToDBU(max_disp_x_microns)
max_disp_y_dbu = design.micronToDBU(max_disp_y_microns)

# Detailed placement uses site units for displacement limits
site_width = site.getWidth()
site_height = site.getHeight()
max_disp_x_site = int(round(max_disp_x_dbu / site_width)) # Use round to avoid potential float precision issues
max_disp_y_site = int(round(max_disp_y_dbu / site_height))

opendp = design.getOpendp()
# Remove filler cells before detailed placement
opendp.removeFillers()
# Perform detailed placement
# detailedPlacement(max_disp_x_site, max_disp_y_site, cell_list, multi_row_aware)
# cell_list is empty string "" for all cells
# multi_row_aware=False
opendp.detailedPlacement(max_disp_x_site, max_disp_y_site, "", False)
print("Initial detailed placement (Pre-CTS) complete.")

# Configure power delivery network (PDN)
print("Configuring Power Delivery Network (PDN)...")
# Set up global power/ground connections
# Find existing power and ground nets or create if needed
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

# Create VDD/VSS nets if they don't exist
if VDD_net is None:
    print("Creating VDD net...")
    VDD_net = odb.dbNet_create(block, "VDD")
if VSS_net is None:
    print("Creating VSS net...")
    VSS_net = odb.dbNet_create(block, "VSS")

# Mark power/ground nets as special nets and set signal type
# Do this after creation if they didn't exist
if VDD_net:
    VDD_net.setSpecial()
    VDD_net.setSigType("POWER")
if VSS_net:
    VSS_net.setSpecial()
    VSS_net.setSigType("GROUND")

# Connect power pins to global nets using global connect
# Map standard VDD/VSS pins to power/ground net for all instances
print("Connecting power/ground pins globally...")
# Using evalTclString for global_connect as it's a common and concise way
design.evalTclString("global_connect VDD -pin_pattern {^VDD$} -inst_pattern {.*}")
design.evalTclString("global_connect VSS -pin_pattern {^VSS$} -inst_pattern {.*}")
print("Global connections complete.")

pdngen = design.getPdnGen()
# Set core power domain with primary power/ground nets
# No switched power or secondary nets specified in the prompt
pdngen.setCoreDomain(power = VDD_net, ground = VSS_net)

# Get metal layers needed for PDN
m1 = db.getTech().findLayer("metal1")
m4 = db.getTech().findLayer("metal4")
m5 = db.getTech().findLayer("metal5")
m6 = db.getTech().findLayer("metal6")
m7 = db.getTech().findLayer("metal7")
m8 = db.getTech().findLayer("metal8")
m9 = db.getTech().findLayer("metal9") # Needed for pin placement check earlier, keep here

# Check if all required layers exist
required_layers_pdn = {"metal1": m1, "metal4": m4, "metal5": m5, "metal6": m6, "metal7": m7, "metal8": m8}
all_layers_exist_pdn = True
for layer_name, layer_obj in required_layers_pdn.items():
    if layer_obj is None:
        print(f"Error: Required layer {layer_name} not found for PDN generation.")
        all_layers_exist_pdn = False

if not all_layers_exist_pdn:
    print("Skipping PDN generation due to missing layers.")
else:
    # Set via cut pitch to 2 μm for connections between layers with grids
    via_cut_pitch_microns = 2.0
    via_cut_pitch_dbu = design.micronToDBU(via_cut_pitch_microns)
    # pdn.makeConnect takes x and y pitch
    pdn_cut_pitch = [via_cut_pitch_dbu, via_cut_pitch_dbu]

    # Set offset to 0 μm for all cases
    offset_microns = 0.0
    offset_dbu = design.micronToDBU(offset_microns)
    # makeRing and makeStrap offset parameters are single value for offset from edge
    # makeRing offset parameter for relative offset is a list [left, bottom, right, top]
    ring_offsets = [offset_dbu, offset_dbu, offset_dbu, offset_dbu] # Use list for makeRing relative offset

    # Get the core domain
    core_domain = pdngen.findDomain("Core")
    if core_domain is None:
        print("Error: Core domain not found. Skipping PDN generation.")
    else:
        domains = [core_domain]
        # Set halo around macros for standard cell grid routing clearance (using 5um macro halo)
        stdcell_grid_halo_microns = 5.0
        stdcell_grid_halo_dbu = design.micronToDBU(stdcell_grid_halo_microns)
        # [left, bottom, right, top] halo around macros to exclude standard cell grid from
        stdcell_grid_halo = [stdcell_grid_halo_dbu, stdcell_grid_halo_dbu, stdcell_grid_halo_dbu, stdcell_grid_halo_dbu]

        for domain in domains:
            # Create the main core grid structure for standard cells
            print("Creating core power grid for standard cells...")
            pdngen.makeCoreGrid(domain = domain,
                name = "core_grid",
                starts_with = pdn.GROUND,  # Start with ground net strap/ring
                pin_layers = [], # Connects to std cell rails on M1, handled by makeFollowpin
                generate_obstructions = [], # No layer obstructions generated by default
                powercell = None,
                powercontrol = None,
                powercontrolnetwork = "STAR", # Default network type
                halo = stdcell_grid_halo # Keep standard cell grid away from macro halo region
                )

        # Get the created core grid objects
        core_grids = pdngen.findGrid("core_grid")
        if not core_grids:
            print("Error: Core grid 'core_grid' not found after creation attempt. Skipping core grid details.")
        else:
            core_grid = core_grids[0] # Assuming a single core grid created

            # Create horizontal power straps on metal1 for standard cell power rail connections (followpin)
            print("Creating M1 followpin straps for standard cells...")
            m1_width_microns = 0.07
            m1_width_dbu = design.micronToDBU(m1_width_microns)
            pdngen.makeFollowpin(grid = core_grid,
                layer = m1,
                width = m1_width_dbu,
                extend = pdn.CORE # Extend within the core area
                )

            # Create power straps on metal4 (vertical) for standard cells
            # Prompt says M4 grid for macros, but original script and typical flow puts M4 grid for standard cells and macro connections start higher up. Sticking to original script structure.
            print("Creating M4 vertical straps for standard cells...")
            m4_width_microns = 1.2
            m4_spacing_microns = 1.2
            m4_pitch_microns = 6.0
            m4_width_dbu = design.micronToDBU(m4_width_microns)
            m4_spacing_dbu = design.micronToDBU(m4_spacing_microns)
            m4_pitch_dbu = design.micronToDBU(m4_pitch_microns)
            pdngen.makeStrap(grid = core_grid,
                layer = m4,
                width = m4_width_dbu,
                spacing = m4_spacing_dbu,
                pitch = m4_pitch_dbu,
                offset = offset_dbu,
                number_of_straps = 0,  # Auto-calculate number of straps
                snap = False, # Don't necessarily snap M4 straps to M1 followpins
                starts_with = pdn.GRID, # Start based on the grid pattern (VSS/VDD)
                extend = pdn.CORE, # Extend within the core for straps
                nets = [])

            # Create power straps on metal7 (horizontal) for standard cells
            print("Creating M7 horizontal straps for standard cells...")
            m7_width_microns = 1.4 # Prompt mentioned M7 rings with 2um width/spacing, but M7 straps had 1.4/1.4 in original script. Sticking to script for straps.
            m7_spacing_microns = 1.4 # Prompt mentioned M7 rings with 2um width/spacing, but M7 straps had 1.4/1.4 in original script. Sticking to script for straps.
            m7_pitch_microns = 10.8 # Prompt mentioned M7 rings with 2um width/spacing, but M7 straps had 10.8 pitch in original script. Sticking to script for straps.
            m7_width_dbu = design.micronToDBU(m7_width_microns)
            m7_spacing_dbu = design.micronToDBU(m7_spacing_microns)
            m7_pitch_dbu = design.micronToDBU(m7_pitch_microns)
            pdngen.makeStrap(grid = core_grid,
                layer = m7,
                width = m7_width_dbu,
                spacing = m7_spacing_dbu,
                pitch = m7_pitch_dbu,
                offset = offset_dbu,
                number_of_straps = 0,
                snap = False,
                starts_with = pdn.GRID,
                extend = pdn.CORE, # Extend within the core for straps
                nets = [])

            # Create power straps on metal8 (vertical) for standard cells
            # Prompt mentioned M8 rings, not straps for std cells, but original script had M8 straps.
            # Sticking to the original script's implementation for straps as it's more typical for a grid.
            # Rings on M7/M8 will be added separately around the core boundary.
            print("Creating M8 vertical straps for standard cells...")
            m8_width_microns = 1.4 # Note: Prompt mentioned M8 rings with 2um width/spacing, but M8 straps had 1.4/1.4 in original script. Sticking to script for straps.
            m8_spacing_microns = 1.4 # Note: Prompt mentioned M8 rings with 2um width/spacing, but M8 straps had 1.4/1.4 in original script. Sticking to script for straps.
            m8_pitch_microns = 10.8 # Note: Prompt mentioned M8 rings with 2um width/spacing, but M8 straps had 10.8 pitch in original script. Sticking to script for straps.
            m8_width_dbu = design.micronToDBU(m8_width_microns)
            m8_spacing_dbu = design.micronToDBU(m8_spacing_microns)
            m8_pitch_dbu = design.micronToDBU(m8_pitch_microns)
            pdngen.makeStrap(grid = core_grid,
                layer = m8,
                width = m8_width_dbu,
                spacing = m8_spacing_dbu,
                pitch = m8_pitch_dbu,
                offset = offset_dbu,
                number_of_straps = 0,
                snap = False,
                starts_with = pdn.GRID,
                extend = pdn.CORE, # Extend within the core for straps
                nets = [])


            # Create power rings around the core area on M7 (horizontal) and M8 (vertical)
            print("Creating M7/M8 core rings...")
            core_ring_width_microns = 2.0
            core_ring_spacing_microns = 2.0
            core_ring_width_dbu = design.micronToDBU(core_ring_width_microns)
            core_ring_spacing_dbu = design.micronToDBU(core_ring_spacing_microns)
            pdngen.makeRing(grid = core_grid,
                layer0 = m7, # Horizontal layer (M7)
                width0 = core_ring_width_dbu,
                spacing0 = core_ring_spacing_dbu,
                layer1 = m8, # Vertical layer (M8)
                width1 = core_ring_width_dbu,
                spacing1 = core_ring_spacing_dbu,
                starts_with = pdn.GRID, # Start based on the grid pattern (VSS/VDD)
                offset = ring_offsets, # Offset relative to the extension boundary (core boundary)
                pad_offset = [0, 0, 0, 0], # Pad offset (unused here as not connecting to pads via rings)
                extend = pdn.BOUNDARY, # Extend to the core boundary to form a ring
                pad_pin_layers = [], # No pad connection via these rings
                nets = [],
                allow_out_of_die = True) # Allow rings to potentially slightly exceed core boundary if needed

    # Create power grid and rings for macro blocks (if any)
    # Prompt says M5/M6 for macros (grid + ring), M4 for macros grid (contradicts M5/M6).
    # Sticking to M5/M6 grid and rings for macros as per the detailed specs provided for M5/M6.
    if len(macros) > 0:
        print("Configuring power grid and rings for macros...")
        # Define strap and ring parameters for macros as per prompt
        macro_grid_width_microns = 1.2 # Applies to M5, M6 straps
        macro_grid_spacing_microns = 1.2 # Applies to M5, M6 straps
        macro_grid_pitch_microns = 6.0 # Applies to M5, M6 straps
        macro_ring_width_microns = 2.0 # Applies to M5, M6 rings
        macro_ring_spacing_microns = 2.0 # Applies to M5, M6 rings

        macro_grid_width_dbu = design.micronToDBU(macro_grid_width_microns)
        macro_grid_spacing_dbu = design.micronToDBU(macro_grid_spacing_microns)
        macro_grid_pitch_dbu = design.micronToDBU(macro_grid_pitch_microns)
        macro_ring_width_dbu = design.micronToDBU(macro_ring_width_microns)
        macro_ring_spacing_dbu = design.micronToDBU(macro_ring_spacing_microns)

        for macro in macros:
            # Create separate instance grid for each macro
            print(f"Creating PDN grid for macro {macro.getName()}...")
            for domain in domains: # Associate macro grid with the core domain
                pdngen.makeInstanceGrid(domain = domain,
                    name = f"macro_grid_{macro.getName()}", # Use macro name for unique grid name
                    starts_with = pdn.GROUND, # Start with ground (VSS/VDD connection order)
                    inst = macro,
                    halo = [0, 0, 0, 0], # Instance grid is specific to the macro boundary, no external halo needed
                    pg_pins_to_boundary = True,  # Connect macro PG pins to boundary (often via followpin internally)
                    default_grid = False, # This is not the default core grid
                    generate_obstructions = [],
                    is_bump = False)

            macro_grids = pdngen.findGrid(f"macro_grid_{macro.getName()}")
            if not macro_grids:
                 print(f"Error: Macro grid 'macro_grid_{macro.getName()}' not found.")
            else:
                macro_grid = macro_grids[0] # Assuming a single grid per instance

                # Create power ring around macro using metal5 (horizontal) and metal6 (vertical)
                print(f"Creating M5/M6 rings around macro {macro.getName()}...")
                pdngen.makeRing(grid = macro_grid,
                    layer0 = m5, # Horizontal layer (M5)
                    width0 = macro_ring_width_dbu,
                    spacing0 = macro_ring_spacing_dbu,
                    layer1 = m6, # Vertical layer (M6)
                    width1 = macro_ring_width_dbu,
                    spacing1 = macro_ring_spacing_dbu,
                    starts_with = pdn.GRID, # Start based on the grid pattern (VSS/VDD)
                    offset = ring_offsets, # Offset relative to the macro boundary (0 offset)
                    pad_offset = [0, 0, 0, 0], # No pad connection via rings
                    extend = pdn.BOUNDARY, # Extend to macro boundary to form a ring
                    pad_pin_layers = [],
                    nets = [])

                # Create power straps on metal5 (horizontal) for macro connections
                print(f"Creating M5 horizontal straps for macro {macro.getName()}...")
                pdngen.makeStrap(grid = macro_grid,
                    layer = m5,
                    width = macro_grid_width_dbu,
                    spacing = macro_grid_spacing_dbu,
                    pitch = macro_grid_pitch_dbu,
                    offset = offset_dbu,
                    number_of_straps = 0,
                    snap = True,  # Snap straps to macro grid coordinates
                    starts_with = pdn.GRID,
                    extend = pdn.RINGS, # Extend straps to connect to macro rings
                    nets = [])

                # Create power straps on metal6 (vertical) for macro connections
                print(f"Creating M6 vertical straps for macro {macro.getName()}...")
                pdngen.makeStrap(grid = macro_grid,
                    layer = m6,
                    width = macro_grid_width_dbu,
                    spacing = macro_grid_spacing_dbu,
                    pitch = macro_grid_pitch_dbu,
                    offset = offset_dbu,
                    number_of_straps = 0,
                    snap = True,
                    starts_with = pdn.GRID,
                    extend = pdn.RINGS, # Extend straps to connect to macro rings
                    nets = [])

    # Create via connections between power grid layers
    print("Creating vias between PDN layers...")
    # Connect core standard cell layers (M1, M4, M7, M8)
    if core_grids:
        print("Adding vias for core grid...")
        # Connect M1 (followpin) to M4 (vertical straps)
        pdngen.makeConnect(grid = core_grid, layer0 = m1, layer1 = m4,
            cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1]) # 2um via pitch
        # Connect M4 (vertical straps) to M7 (horizontal straps/rings)
        pdngen.makeConnect(grid = core_grid, layer0 = m4, layer1 = m7,
            cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1]) # 2um via pitch
        # Connect M7 (horizontal straps/rings) to M8 (vertical straps/rings)
        pdngen.makeConnect(grid = core_grid, layer0 = m7, layer1 = m8,
            cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1]) # 2um via pitch

    # Connect macro grid layers (M5, M6) and connect macro grid to core grid (M4-M5, M6-M7)
    if len(macros) > 0 and core_grids:
        print("Adding vias for macro grids and connections to core grid...")
        for macro in macros:
            macro_grids = pdngen.findGrid(f"macro_grid_{macro.getName()}")
            if macro_grids:
                macro_grid = macro_grids[0]
                # Connect metal4 (from core grid) to metal5 (macro grid)
                pdngen.makeConnect(grid = macro_grid, layer0 = m4, layer1 = m5,
                    cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1]) # 2um via pitch
                # Connect metal5 to metal6 (macro grid layers)
                pdngen.makeConnect(grid = macro_grid, layer0 = m5, layer1 = m6,
                    cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1]) # 2um via pitch
                # Connect metal6 (macro grid) to metal7 (core grid)
                pdngen.makeConnect(grid = macro_grid, layer0 = m6, layer1 = m7,
                    cut_pitch_x = pdn_cut_pitch[0], cut_pitch_y = pdn_cut_pitch[1]) # 2um via pitch


    # Generate the final power delivery network geometry
    print("Building PDN grids...")
    pdngen.checkSetup()  # Verify configuration
    pdngen.buildGrids(False)  # Build the power grid geometry
    pdngen.writeToDb(True, )  # Write power grid shapes to the design database
    pdngen.resetShapes()  # Reset temporary shapes used during generation
    print("PDN generation complete.")

# Configure and run clock tree synthesis (CTS)
print("Performing clock tree synthesis (CTS)...")
cts = design.getTritonCts()
# Set RC values for clock and signal nets via TCL commands
# This is common practice
# Note: Resistance and capacitance values are per unit length
design.evalTclString("set_wire_rc -clock -resistance 0.0435 -capacitance 0.0817")
design.evalTclString("set_wire_rc -signal -resistance 0.0435 -capacitance 0.0817")

# Configure clock buffers to use BUF_X3
# Assuming BUF_X3 is a valid library cell name with a buffer function
cts.setBufferList("BUF_X3")
cts.setRootBuffer("BUF_X3")
cts.setSinkBuffer("BUF_X3")
# Set the clock net name for CTS (assuming the clock net created earlier is named "core_clock")
cts.setClockNets("core_clock")
# Run CTS
cts.runTritonCts()
print("Clock tree synthesis complete.")


# Run final detailed placement (Post-CTS)
print("Performing final detailed placement (Post-CTS)...")
# Allow 0.5um x-displacement and 1um y-displacement
# Use already calculated site units displacements (max_disp_x_site, max_disp_y_site)
# Remove filler cells before detailed placement
opendp.removeFillers()
# Perform detailed placement
# detailedPlacement(max_disp_x_site, max_disp_y_site, cell_list, multi_row_aware)
# cell_list is empty string "" for all cells
# multi_row_aware=False
opendp.detailedPlacement(max_disp_x_site, max_disp_y_site, "", False)
print("Final detailed placement (Post-CTS) complete.")

# Insert filler cells to fill gaps after placement
print("Inserting filler cells...")
# Get filler masters - typically these have the CORE_SPACER type
filler_masters = list()
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

if not filler_masters:
    print("Warning: No filler cells (type CORE_SPACER) found in library! Skipping filler placement.")
else:
    # Filler cell naming convention
    filler_cells_prefix = "FILLCELL_"
    # fillerPlacement(filler_masters, prefix, verbose)
    opendp.fillerPlacement(filler_masters = filler_masters,
                                     prefix = filler_cells_prefix,
                                     verbose = False)
    print("Filler placement complete.")

# Configure and run global routing
print("Performing global routing...")
grt = design.getGlobalRouter()
# Set routing layer ranges for signal and clock nets (M1 to M6)
m1_layer_route = db.getTech().findLayer("metal1")
m6_layer_route = db.getTech().findLayer("metal6")

if m1_layer_route is None or m6_layer_route is None:
    print("Error: metal1 or metal6 layer not found for routing layer range. Skipping routing.")
else:
    m1_level = m1_layer_route.getRoutingLevel()
    m6_level = m6_layer_route.getRoutingLevel()

    grt.setMinRoutingLayer(m1_level)
    grt.setMaxRoutingLayer(m6_level)
    # Use the same layer range for clock nets
    grt.setMinLayerForClock(m1_level)
    grt.setMaxLayerForClock(m6_level)
    grt.setAdjustment(0.5) # Default adjustment, can be tuned based on congestion
    grt.setVerbose(True)
    # Set the number of global router iterations
    grt.setIterationNum(10)
    print("Global router iterations set to 10.")

    # Run global routing
    # Passing True calculates estimated wire parasitics
    grt.globalRoute(True)
    print("Global routing complete.")

    # Configure and run detailed routing
    print("Performing detailed routing...")
    drter = design.getTritonRoute()
    params = drt.ParamStruct()
    # Set routing layer range for detailed routing (M1 to M6)
    # Use layer names for TritonRoute parameters
    params.bottomRoutingLayer = "metal1"
    params.topRoutingLayer = "metal6"

    # Other detailed routing parameters can be set as needed
    # params.outputMazeFile = ""
    # params.outputDrcFile = ""
    # params.outputCmapFile = ""
    # params.outputGuideCoverageFile = ""
    # params.dbProcessNode = "" # Technology node string, if required
    params.enableViaGen = True
    params.drouteEndIter = 1 # Number of detailed routing iterations (default is often 1)
    # params.viaInPinBottomLayer = "" # Can set if specific via-in-pin layers are needed
    # params.viaInPinTopLayer = ""
    params.orSeed = -1 # Random seed
    params.orK = 0 # Not used for standard routing
    params.verbose = 1
    params.cleanPatches = True
    params.doPa = True # Perform pin access analysis
    params.singleStepDR = False
    params.minAccessPoints = 1
    params.saveGuideUpdates = False # Set to True for debugging guide updates

    drter.setParams(params)
    # Run detailed routing
    drter.main()
    print("Detailed routing complete.")

    # Perform IR drop analysis on M1 layer using psm module
    print("Performing IR drop analysis on metal1...")
    ir_drop_output_file = "ir_drop_m1.rpt"
    psm_inst = design.getPowerSpectrum()

    if psm_inst is None:
        print("Error: Could not get Power Spectrum (psm) instance. Skipping IR drop analysis.")
    else:
        # Find the metal1 layer by name for the layers list
        m1_layer_psm = db.getTech().findLayer("metal1")
        if m1_layer_psm is None:
             print("Error: metal1 layer not found for IR drop analysis. Skipping analysis.")
        else:
            psm_params = psm.RailAnalysisParams()
            psm_params.power_nets = ["VDD"]
            psm_params.ground_nets = ["VSS"]
            psm_params.method = "static" # Or "dynamic"
            psm_params.layers = ["metal1"] # List of layer names
            psm_params.output_file = ir_drop_output_file
            # Add parameters for saving results to DB if needed (e.g., voltage maps)
            # psm_params.vdrop_layer = "vdd_vdrop"
            # psm_params.vsource_layer = "vss_vdrop"
            # psm_params.ir_layer = "ir_drop"

            try:
                psm_inst.rail_analysis(psm_params)
                print(f"IR drop analysis on metal1 complete. Report saved to {ir_drop_output_file}")
            except Exception as e:
                print(f"Error during IR drop analysis: {e}")


    # Write final DEF file
    print("Writing final DEF file: final.def")
    design.writeDef("final.def")
    print("DEF file written.")

    # Write final Verilog file (optional, but good practice)
    print("Writing final Verilog file: final.v")
    # Ensure the design is finalized/extracted if needed before writing Verilog post-route
    design.evalTclString("write_verilog final.v")
    print("Verilog file written.")

    print("OpenROAD flow script execution complete.")