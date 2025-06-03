import odb
import pdn
import drt
import openroad as ord
import sys

# Get the OpenROAD database object and design block
# Design block is only available after read_verilog and link_design
db = ord.get_db()
design = ord.get_design()

print("Starting OpenROAD script execution...")

#------------------------------------------------------------------------------
# Read Input Files (LEF, Liberty, Verilog)
#------------------------------------------------------------------------------
print("Reading input files...")
# Replace with your actual file paths
# Ensure these paths are correct and the files exist
lef_file = "path/to/your/tech.lef"       # Technology LEF file
lib_file = "path/to/your/cells.lib"      # Standard cell Liberty file
verilog_file = "path/to/your/netlist.v"  # Synthesized Verilog netlist

try:
    # Read technology and library files using Tcl commands as per feedback
    design.evalTclString(f"read_lef {lef_file}")
    design.evalTclString(f"read_lib {lib_file}")

    # Read the synthesized netlist and create the design block
    design.evalTclString(f"read_verilog {verilog_file}")

    # Link the design block to the library
    # Assumes the top module name matches the design name after reading verilog
    # Get the block name from the database after reading verilog
    block = db.getChip().getBlock() # Use db to get the block after read_verilog

    if block is None:
        raise Exception("Could not create design block from verilog.")

    top_module_name = block.getName()
    design.evalTclString(f"link_design {top_module_name}")

    # Re-get block and tech objects after linking to ensure they are valid
    block = db.getChip().getBlock()
    tech = db.getTech() # Use db.getTech() after reading LEF

    if block is None or tech is None:
         raise Exception("Design block or technology database is not initialized after linking.")

    print("Input files read and design linked.")
    can_proceed = True

except Exception as e:
    print(f"Error reading input files or linking design: {e}")
    can_proceed = False
    # In a real flow, you would sys.exit(1) here.
    # For this example, we'll print the error and stop subsequent steps.


if can_proceed:
    #------------------------------------------------------------------------------
    # Create Clock
    #------------------------------------------------------------------------------
    print("Creating clock...")
    # Define clock period in nanoseconds and port name
    clock_period_ns = 20
    clock_port_name = "clk_i"
    clock_name = "core_clock"

    # Convert clock period to picoseconds for create_clock command
    clock_period_ps = int(clock_period_ns * 1000)

    # Check if clock port exists and create clock
    clock_port = block.findBTerm(clock_port_name)
    if clock_port is None:
        print(f"Error: Clock port '{clock_port_name}' not found! Cannot create clock.")
        # Set flag to prevent subsequent steps that rely on clock
        can_proceed_clock = False
    else:
        # Create the clock signal on the specified port using Tcl
        design.evalTclString(f"create_clock -period {clock_period_ps} [get_ports {clock_port_name}] -name {clock_name}")
        # Propagate the clock signal using Tcl (often required for timing analysis/CTS)
        design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")
        print(f"Clock '{clock_name}' created with period {clock_period_ns} ns on port '{clock_port_name}'.")
        can_proceed_clock = True

    #------------------------------------------------------------------------------
    # Floorplanning
    #------------------------------------------------------------------------------
    print("Performing floorplanning...")
    # Set target utilization and core-to-die margin for floorplan initialization
    core_utilization = 0.45
    core_margin_micron = 10.0 # spacing between core and die boundary

    # Find a standard cell site from the technology file
    site = None
    # Iterate through libs and masters to find a CORE site with a valid site type
    if tech and db.getLibs():
        for lib in db.getLibs():
            for master in lib.getMasters():
                if master.getType() == "CORE":
                    # Find a site for a CORE master - check if site origins exist and have a site object
                    if master.getSiteOrigins():
                         site_origin = master.getSiteOrigins()[0]
                         if site_origin:
                             site = site_origin.getSite()
                             if site:
                                break
            if site:
                break

    if site is None:
        print("Error: Could not find a valid standard cell site in the technology library. Cannot create floorplan.")
        can_proceed = False # Cannot proceed without floorplan
    else:
        site_name = site.getName()
        # Use Tcl command for floorplan creation with utilization and margin
        design.evalTclString(f"create_floorplan -core_utilization {core_utilization} -core_margin {core_margin_micron} -site {site_name}")
        print(f"Floorplan created with core utilization {core_utilization} and core margin {core_margin_micron} um using site '{site_name}'.")

        # Make tracks after floorplanning is initialized
        # Tracks are required for standard cell placement and routing
        floorplan = block.getFloorplan()
        if floorplan:
            floorplan.makeTracks()
            print("Tracks created.")
        else:
             print("Warning: Floorplan object not found after creation. Tracks not made.")

    # Ensure we can still proceed after floorplanning attempt
    if not can_proceed:
        print("Script stopped early due to floorplan creation errors.")
    else:
        #------------------------------------------------------------------------------
        # IO Pin Placement
        #------------------------------------------------------------------------------
        print("Placing I/O pins...")
        io_placer = design.getIOPlacer()
        params = io_placer.getParameters()

        # Default parameters might be fine, but setting explicitly can be good
        # Setting min_distance and corner_avoidance to 0 as requested implicitly by not specifying
        params.setMinDistanceInTracks(False) # Use DBU for minimum distance
        params.setMinDistance(design.micronToDBU(0))
        params.setCornerAvoidance(design.micronToDBU(0))
        params.setRandSeed(42) # Use a fixed seed for reproducibility

        # Place I/O pins on metal8 (horizontal) and metal9 (vertical) layers as requested
        m8 = tech.findLayer("metal8")
        m9 = tech.findLayer("metal9")

        if m8 and m9:
            io_placer.addHorLayer(m8)
            io_placer.addVerLayer(m9)
            # Run IO placement annealing
            io_placer.runAnnealing(False) # False means no gui
            print("I/O pins placed.")
        else:
            missing_io_layers = []
            if not m8: missing_io_layers.append("metal8")
            if not m9: missing_io_layers.append("metal9")
            print(f"Warning: Skipping IO placement. Required layer(s) not found: {', '.join(missing_io_layers)}.")

        #------------------------------------------------------------------------------
        # Macro Placement
        #------------------------------------------------------------------------------
        print("Placing macros...")
        # Get all instances that are macros (have BLOCK masters)
        # Check for master existence before calling isBlock()
        macros = [inst for inst in block.getInsts() if inst.getMaster() and inst.getMaster().isBlock()]

        if len(macros) > 0:
            print(f"Found {len(macros)} macros. Running macro placement.")
            mpl = design.getMacroPlacer()
            # Define macro placement parameters from prompt
            fence_lx_micron = 32.0
            fence_ly_micron = 32.0
            fence_ux_micron = 55.0
            fence_uy_micron = 60.0
            halo_micron = 5.0
            min_macro_spacing_micron = 5.0

            # Run macro placement with specified parameters
            # Note: The prompt specifies placing macros *within* a bounding box.
            # MacroPlacer's `place` function often places macros considering fences
            # and other constraints. If exact placement at specific coords is needed,
            # `dbInst.setLocation` would be used after sorting/calculating positions.
            # Assuming `place` is intended to find valid positions for the macros
            # within the fence, considering halo and spacing.
            mpl.place(
                num_threads = 64,
                max_num_macro = len(macros), # Place all found macros
                min_macro_macro_dist = min_macro_spacing_micron,
                halo_width = halo_micron,
                halo_height = halo_micron,
                fence_lx = fence_lx_micron,
                fence_ly = fence_ly_micron,
                fence_ux = fence_ux_micron,
                fence_uy = fence_uy_micron,
                # Other parameters are left at reasonable defaults or derived
                # from common usage if not specified in prompt.
                area_weight = 0.1,
                outline_weight = 100.0,
                wirelength_weight = 100.0,
                guidance_weight = 10.0,
                fence_weight = 10.0,
                boundary_weight = 50.0,
                notch_weight = 10.0,
                macro_blockage_weight = 10.0,
                pin_access_th = 0.0,
                target_util = 0.25, # This utility applies to the area *around* macros, adjust as needed
                target_dead_space = 0.05,
                min_ar = 0.33, # Aspect ratio constraint
                bus_planning_flag = False,
                report_directory = "" # Optional: directory for placement reports
            )
            print("Macro placement complete.")
        else:
            print("No macros found. Skipping macro placement.")

        #------------------------------------------------------------------------------
        # Global Placement (Standard Cells)
        #------------------------------------------------------------------------------
        print("Running Global Placement for standard cells...")
        gpl = design.getReplace()
        # Configure global placement parameters
        gpl.setTimingDrivenMode(False) # No timing data available yet
        gpl.setRoutabilityDrivenMode(True) # Enable routability consideration
        gpl.setUniformTargetDensityMode(True)
        gpl.setInitialPlaceMaxIter(5)
        gpl.setInitDensityPenalityFactor(0.05)

        # Run the two stages of RePlace
        gpl.doInitialPlace(threads = 4)
        gpl.doNesterovPlace(threads = 4)
        gpl.reset() # Reset internal state (important before subsequent runs or other tools)
        print("Global Placement complete.")

        #------------------------------------------------------------------------------
        # Detailed Placement (Pre-CTS/PDN)
        #------------------------------------------------------------------------------
        print("Running initial Detailed Placement...")
        dp = design.getOpendp()
        # Set maximum displacement to 0 um as requested
        max_disp_x_micron = 0.0
        max_disp_y_micron = 0.0
        max_disp_x_dbu = design.micronToDBU(max_disp_x_micron)
        max_disp_y_dbu = design.micronToDBU(max_disp_y_micron)

        # Detailed placement to fix standard cells to legal sites before CTS/PDN
        dp.removeFillers() # Remove any existing fillers
        dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False) # Args: max_disp_x, max_disp_y, cell_list_file, is_incremental
        print("Initial Detailed Placement complete (0 displacement).")

        #------------------------------------------------------------------------------
        # Power Delivery Network (PDN) Generation
        #------------------------------------------------------------------------------
        print("Configuring Power Delivery Network...")
        pdngen = design.getPdnGen()

        # Set up global power/ground connections by marking nets as special
        # Using Tcl is often more robust for finding/creating nets like VDD/VSS
        # Replace 'VDD' and 'VSS' with actual net names if they are different
        design.evalTclString("set_nets_special -power_ground [get_nets -hierarchical {VDD VSS}]")

        # Find existing power and ground nets using Python (after Tcl sets them special)
        VDD_net = block.findNet("VDD")
        VSS_net = block.findNet("VSS")
        switched_power = None
        secondary = list() # List of secondary power/ground pairs

        if VDD_net is None or VSS_net is None:
             print("Error: VDD or VSS net not found or not marked special. Cannot configure core domain.")
             can_proceed_pdn = False
        else:
            # Connect standard cell power pins to the global VDD/VSS nets using globalConnect
            # This connects VDD/VSS pins on instances like 'VDD' and 'VSS' to the corresponding net objects
            # Replace 'VDD' and 'VSS' pin names if different
            design.evalTclString("global_connect -inst * -pin VDD -net VDD")
            design.evalTclString("global_connect -inst * -pin VSS -net VSS")
            print("Configured global power/ground connections for standard cells.")

            # Set core power domain with primary power/ground nets
            pdngen.setCoreDomain(power = VDD_net,
                                 switched_power = switched_power, # Not requested
                                 ground = VSS_net,
                                 secondary = secondary) # Not requested
            print("Set core power domain.")
            can_proceed_pdn = True

        if can_proceed_pdn:
            # Define parameters in DBU
            via_cut_pitch_micron = 2.0 # Via pitch between two grids
            pdn_cut_pitch_x = design.micronToDBU(via_cut_pitch_micron)
            pdn_cut_pitch_y = design.micronToDBU(via_cut_pitch_micron)
            offset_micron = 0.0 # Offset 0 um for all cases as requested
            offset_dbu = design.micronToDBU(offset_micron)
            ring_offset_dbu = [offset_dbu] * 4 # Offset [left, bottom, right, top] for ring

            # Find required metal layers from technology
            m1 = tech.findLayer("metal1")
            m4 = tech.findLayer("metal4")
            m5 = tech.findLayer("metal5")
            m6 = tech.findLayer("metal6")
            m7 = tech.findLayer("metal7")
            m8 = tech.findLayer("metal8")

            required_layers = { "metal1":m1, "metal4":m4, "metal5":m5, "metal6":m6, "metal7":m7, "metal8":m8 }
            missing_layers = [name for name, layer in required_layers.items() if layer is None]

            if missing_layers:
                print(f"Error: Required metal layers not found for PDN: {', '.join(missing_layers)}. Skipping PDN generation.")
                can_proceed_pdn = False # Cannot proceed with PDN if layers are missing

            if can_proceed_pdn:
                # Create core grid structure for standard cells and top-level backbone
                domains = pdngen.findDomain("Core")
                if not domains:
                    print("Error: Core domain not found. Cannot build core PDN grid.")
                    can_proceed_pdn = False
                else:
                    core_domain = domains[0]
                    # Make the main core grid definition object
                    pdngen.makeCoreGrid(domain = core_domain,
                        name = "core_pwr_grid",
                        starts_with = pdn.GROUND, # Specify which net pattern starts first
                        # pin_layers: List of layers to connect to cell pins (M1 followpin handles std cells)
                        # generate_obstructions: List of layers to generate blockages on
                        # powercell, powercontrol, powercontrolnetwork: For power gating, not requested
                        pin_layers = [],
                        generate_obstructions = [],
                        powercell = None,
                        powercontrol = None,
                        powercontrolnetwork = "") # Default network type

                    print("Created core grid structure 'core_pwr_grid'.")

                    core_grids = pdngen.findGrid("core_pwr_grid")
                    if not core_grids:
                        print("Error: Core PDN grid 'core_pwr_grid' not found after creation.")
                        can_proceed_pdn = False
                    else:
                        core_grid = core_grids[0]

                        # Add PDN rings around the core area on M7 and M8 (Prompt request)
                        core_ring_width_micron = 2.0
                        core_ring_spacing_micron = 2.0
                        core_ring_width = design.micronToDBU(core_ring_width_micron)
                        core_ring_spacing = design.micronToDBU(core_ring_spacing_micron)

                        # makeRing requires width and spacing for each layer
                        pdngen.makeRing(grid = core_grid,
                            layer0 = m7, width0 = core_ring_width, spacing0 = core_ring_spacing,
                            layer1 = m8, width1 = core_ring_width, spacing1 = core_ring_spacing,
                            starts_with = pdn.GRID, # Start ring pattern from core grid boundary
                            offset = ring_offset_dbu, # Offset from the boundary
                            pad_offset = [0]*4, # Pad offset (usually 0)
                            extend = False, # Do not extend rings beyond the core boundary
                            # nets: List of nets for this ring, default is all domain nets
                            # pad_pin_layers: Layers to connect to ring from boundary pads
                            nets = [],
                            pad_pin_layers = [],
                            allow_out_of_die = True) # Allow rings to go outside die if needed
                        print(f"Added core rings on {m7.getName()} and {m8.getName()} (width {core_ring_width_micron}um, spacing {core_ring_spacing_micron}um, offset {offset_micron}um).")

                        # Add horizontal power straps on metal1 following standard cell pins (Prompt request for std cells)
                        m1_strap_width_micron = 0.07
                        m1_strap_width = design.micronToDBU(m1_strap_width_micron)
                        # makeFollowpin connects to pins on the specified layer within standard cells
                        pdngen.makeFollowpin(grid = core_grid,
                            layer = m1,
                            width = m1_strap_width,
                            offset = offset_dbu,
                            extend = pdn.CORE) # Extend followpin straps to the core boundary
                        print(f"Added followpin straps on {m1.getName()} (width {m1_strap_width_micron}um, offset {offset_micron}um).")

                        # Add power straps on metal7 and metal8 for the core grid (Prompt request)
                        # Prompt asked for M7/M8 grid for std cells/macros. M8 rings are already done.
                        # Adding M7 straps as part of the core grid backbone.
                        m7_strap_width_micron = 1.4
                        m7_strap_spacing_micron = 1.4
                        m7_strap_pitch_micron = 10.8
                        m7_strap_width = design.micronToDBU(m7_strap_width_micron)
                        m7_strap_spacing = design.micronToDBU(m7_strap_spacing_micron)
                        m7_strap_pitch = design.micronToDBU(m7_strap_pitch_micron)

                        pdngen.makeStrap(grid = core_grid,
                            layer = m7,
                            width = m7_strap_width,
                            spacing = m7_strap_spacing, # makeStrap uses spacing OR pitch. Pitch is provided.
                            pitch = m7_strap_pitch,
                            offset = offset_dbu,
                            number_of_straps = 0, # 0 means automatically determine number based on pitch/extent
                            snap = True, # Snap straps to manufacturing grid
                            starts_with = pdn.GRID, # Start pattern relative to the grid boundary
                            extend = pdn.RINGS, # Extend straps to connect to the core rings
                            nets = []) # Apply to all nets in the domain
                        print(f"Added straps on {m7.getName()} (width {m7_strap_width_micron}um, spacing {m7_strap_spacing_micron}um, pitch {m7_strap_pitch_micron}um, offset {offset_micron}um).")

                        # Add via connections within the core grid layers
                        # M1 (followpin) up to M7 (straps) and M8 (rings)
                        pdngen.makeConnect(grid = core_grid,
                            layer0 = m1, layer1 = m7,
                            cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y) # Via pitch 2um
                        print(f"Added vias between {m1.getName()} and {m7.getName()} (pitch {via_cut_pitch_micron}um).")

                        pdngen.makeConnect(grid = core_grid,
                            layer0 = m7, layer1 = m8,
                            cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y) # Via pitch 2um
                        print(f"Added vias between {m7.getName()} and {m8.getName()} (pitch {via_cut_pitch_micron}um).")


                # Create power grid for macro blocks (if any) - Prompt request for M4, M5, M6 grids for macros
                macros = [inst for inst in block.getInsts() if inst.getMaster() and inst.getMaster().isBlock()]
                if len(macros) > 0:
                    # Macro grid parameters - Prompt request for M4, M5, M6 grids for macros
                    macro_strap_width_micron = 1.2
                    macro_strap_spacing_micron = 1.2 # Spacing requested for M4
                    macro_strap_pitch_micron = 6.0 # Pitch requested for M4, M5, M6

                    macro_strap_width = design.micronToDBU(macro_strap_width_micron)
                    # Note: makeStrap uses spacing OR pitch. Pitch is requested.
                    # Ensure consistent interpretation of pitch/spacing. Assuming pitch overrides spacing for strap pattern.
                    macro_strap_spacing = design.micronToDBU(macro_strap_spacing_micron) # Keep spacing variable if needed elsewhere
                    macro_strap_pitch = design.micronToDBU(macro_strap_pitch_micron)

                    # Use the halo defined during macro placement for PDN routing exclusion around macros
                    # The macro placer's halo should be accessible if the placer ran, but defining it again ensures it's available
                    pdn_macro_halo_micron = halo_micron # Re-use halo value from macro placement
                    pdn_macro_halo = [design.micronToDBU(pdn_macro_halo_micron)] * 4 # [left, bottom, right, top]

                    print(f"Configuring PDN for {len(macros)} macros.")
                    for i, macro_inst in enumerate(macros):
                        macro_inst_name = macro_inst.getName()
                        macro_grid_name = f"macro_grid_{macro_inst_name}"
                        print(f"  Configuring PDN for macro '{macro_inst_name}'...")
                        # Create instance grid for each macro
                        pdngen.makeInstanceGrid(domain = core_domain, # Macros belong to the core domain
                            name = macro_grid_name,
                            starts_with = pdn.GROUND, # Specify which net pattern starts first
                            inst = macro_inst,
                            halo = pdn_macro_halo, # Keep PDN routing outside the macro halo
                            pg_pins_to_boundary = True, # Connect macro power pins to the grid boundary
                            default_grid = False, # This is an instance-specific grid, not the default core grid
                            generate_obstructions = [], # Do not generate new obstructions
                            is_bump = False) # Not a bump pad

                        macro_grids = pdngen.findGrid(macro_grid_name)

                        if not macro_grids:
                             print(f"Error: Could not find macro instance grid '{macro_grid_name}' after creation.")
                        else:
                            macro_grid = macro_grids[0]

                            # Add power straps on metal4 (Prompt request)
                            # Use the specified pitch (6um) and width (1.2um)
                            pdngen.makeStrap(grid = macro_grid,
                                layer = m4,
                                width = macro_strap_width,
                                spacing = macro_strap_spacing, # Spacing here might define the gap *between* straps if pitch isn't used, but pitch is requested.
                                pitch = macro_strap_pitch, # Using pitch as primary driver for strap density
                                offset = offset_dbu,
                                number_of_straps = 0,
                                snap = True,
                                starts_with = pdn.GRID,
                                extend = pdn.CORE, # Extend straps to connect to the core grid boundary
                                nets = [])
                            print(f"    Added straps on {m4.getName()} (width {macro_strap_width_micron}um, spacing {macro_strap_spacing_micron}um, pitch {macro_strap_pitch_micron}um, offset {offset_micron}um).")

                            # Add power straps on metal5 (Prompt request)
                            pdngen.makeStrap(grid = macro_grid,
                                layer = m5,
                                width = macro_strap_width,
                                spacing = macro_strap_spacing,
                                pitch = macro_strap_pitch,
                                offset = offset_dbu,
                                number_of_straps = 0,
                                snap = True,
                                starts_with = pdn.GRID,
                                extend = pdn.CORE,
                                nets = [])
                            print(f"    Added straps on {m5.getName()} (width {macro_strap_width_micron}um, spacing {macro_strap_spacing_micron}um, pitch {macro_strap_pitch_micron}um, offset {offset_micron}um).")

                            # Add power straps on metal6 (Prompt request)
                            pdngen.makeStrap(grid = macro_grid,
                                layer = m6,
                                width = macro_strap_width,
                                spacing = macro_strap_spacing,
                                pitch = macro_strap_pitch,
                                offset = offset_dbu,
                                number_of_straps = 0,
                                snap = True,
                                starts_with = pdn.GRID,
                                extend = pdn.CORE,
                                nets = [])
                            print(f"    Added straps on {m6.getName()} (width {macro_strap_width_micron}um, spacing {macro_strap_spacing_micron}um, pitch {macro_strap_pitch_micron}um, offset {offset_micron}um).")


                            # Add via connections within macro power grid layers and connecting to core grid layers
                            # Connect M4 to M5 (macro grid layers)
                            pdngen.makeConnect(grid = macro_grid,
                                layer0 = m4, layer1 = m5,
                                cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y) # Via pitch 2um
                            print(f"    Added vias between {m4.getName()} and {m5.getName()} (pitch {via_cut_pitch_micron}um).")

                            # Connect M5 to M6 (macro grid layers)
                            pdngen.makeConnect(grid = macro_grid,
                                layer0 = m5, layer1 = m6,
                                cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y) # Via pitch 2um
                            print(f"    Added vias between {m5.getName()} and {m6.getName()} (pitch {via_cut_pitch_micron}um).")

                            # Connect macro grids (M4, M5, M6) up to core grid/rings (M7, M8)
                            # Need connects from macro grid layers up to core backbone/rings
                            # Connecting M4, M5, M6 to M7 and M8
                            pdngen.makeConnect(grid = macro_grid,
                                layer0 = m4, layer1 = m7,
                                cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y)
                            print(f"    Added vias between {m4.getName()} and {m7.getName()} (pitch {via_cut_pitch_micron}um).")

                            pdngen.makeConnect(grid = macro_grid,
                                layer0 = m5, layer1 = m7,
                                cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y)
                            print(f"    Added vias between {m5.getName()} and {m7.getName()} (pitch {via_cut_pitch_micron}um).")

                            pdngen.makeConnect(grid = macro_grid,
                                layer0 = m6, layer1 = m7,
                                cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y)
                            print(f"    Added vias between {m6.getName()} and {m7.getName()} (pitch {via_cut_pitch_micron}um).")

                            pdngen.makeConnect(grid = macro_grid,
                                layer0 = m6, layer1 = m8,
                                cut_pitch_x = pdn_cut_pitch_x, cut_pitch_y = pdn_cut_pitch_y)
                            print(f"    Added vias between {m6.getName()} and {m8.getName()} (pitch {via_cut_pitch_micron}um).")

                else:
                    print("No macros found. Skipping macro PDN generation.")

                # Finalize PDN generation
                # Check setup first to catch issues before building
                pdngen.checkSetup()
                # Build the geometric shapes for all defined grids
                pdngen.buildGrids(False) # False for non-incremental build
                # Write the generated shapes to the OpenROAD database
                pdngen.writeToDb(True) # True means replace existing shapes
                # Reset internal PDN generator state (recommended after build)
                pdngen.resetShapes()
                print("PDN generation complete.")
            else:
                 print("PDN generation skipped due to configuration errors or missing layers.")
                 can_proceed_pdn = False # Ensure flag is false if layers were missing

        else: # if not can_proceed_pdn at domain setup
             print("PDN generation skipped due to missing VDD/VSS nets or domain configuration issues.")


        #------------------------------------------------------------------------------
        # Clock Tree Synthesis (CTS)
        #------------------------------------------------------------------------------
        # Only run CTS if clock was created successfully and PDN is available (CTS needs PDN)
        if can_proceed_clock and can_proceed_pdn:
            print("Running Clock Tree Synthesis...")
            # Set RC values for clock and signal nets using Tcl commands as per prompt
            design.evalTclString("set_wire_rc -clock -resistance 0.0435 -capacitance 0.0817")
            design.evalTclString("set_wire_rc -signal -resistance 0.0435 -capacitance 0.0817")
            print("Set wire RC values (R=0.0435, C=0.0817) for clock and signal nets.")

            cts = design.getTritonCts()
            # Accessing parameters struct is less common for basic setup like buffer list
            # parms = cts.getParms()

            # Configure clock buffers to use BUF_X3 as requested
            cts_buffer_name = "BUF_X3"
            lib_master = None
            # Check if the buffer exists in the library before setting
            if db.getLibs():
                for lib in db.getLibs():
                    lib_master = lib.findMaster(cts_buffer_name)
                    if lib_master:
                        break

            if lib_master:
                # Set the list of buffers CTS can use (usually includes inverters too)
                # For this prompt, only BUF_X3 is mentioned. Using just the buffer.
                cts.setBufferList(cts_buffer_name)
                # Set specific buffers for root and sinks (optional, but common)
                cts.setRootBuffer(cts_buffer_name)
                cts.setSinkBuffer(cts_buffer_name) # Setting sink buffer is common practice
                print(f"Configured CTS to use buffer '{cts_buffer_name}'.")

                # Run CTS
                cts.runTritonCts()
                print("Clock Tree Synthesis complete.")
                can_proceed_cts = True
            else:
                print(f"Warning: Clock buffer '{cts_buffer_name}' not found in library. Skipping CTS.")
                can_proceed_cts = False
        else: # if not can_proceed_clock or not can_proceed_pdn
             print("Clock Tree Synthesis skipped because clock or PDN setup failed.")
             can_proceed_cts = False


        #------------------------------------------------------------------------------
        # Detailed Placement (Post-CTS)
        #------------------------------------------------------------------------------
        # Run post-CTS DP only if CTS ran successfully
        if can_proceed_cts:
            print("Running post-CTS Detailed Placement...")
            # Use the same maximum displacement (0um/0um) as specified earlier
            max_disp_x_micron = 0.0
            max_disp_y_micron = 0.0
            max_disp_x_dbu = design.micronToDBU(max_disp_x_micron)
            max_disp_y_dbu = design.micronToDBU(max_disp_y_micron)

            dp = design.getOpendp() # Get the detailed placer again (or re-use if already got it)
            # Detailed placement to fix locations after CTS might have moved cells or added buffers
            dp.removeFillers() # Remove fillers added by pre-CTS DP or CTS
            dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False) # Use 0 displacement
            print("Post-CTS Detailed Placement complete (0 displacement).")
            can_proceed_post_cts_dp = True
        else:
             print("Post-CTS Detailed Placement skipped because CTS was skipped.")
             can_proceed_post_cts_dp = False


        #------------------------------------------------------------------------------
        # Insert Filler Cells
        #------------------------------------------------------------------------------
        # Insert fillers after final Detailed Placement
        if can_proceed_post_cts_dp:
            print("Inserting filler cells...")
            dp = design.getOpendp() # Get detailed placer
            filler_masters = list()
            filler_cells_prefix = "FILLCELL_" # Prefix for generated filler instance names
            # Find all masters in the library that are CORE_SPACER type (filler cells)
            if db.getLibs():
                for lib in db.getLibs():
                    for master in lib.getMasters():
                        if master.getType() == "CORE_SPACER":
                             filler_masters.append(master)

            if len(filler_masters) == 0:
                print("Warning: No filler cells (CORE_SPACER) found in library! Skipping filler placement.")
            else:
                # Place fillers in empty spaces
                dp.fillerPlacement(filler_masters = filler_masters,
                                         prefix = filler_cells_prefix,
                                         verbose = False) # Set to True for more info
                print(f"Inserted filler cells (found {len(filler_masters)} types).")
        else:
             print("Filler insertion skipped because post-CTS detailed placement was skipped.")


        #------------------------------------------------------------------------------
        # Global Routing
        #------------------------------------------------------------------------------
        # Global routing requires layout information (placement, PDN)
        if can_proceed_post_cts_dp: # Assuming DP is the last step before routing prep
            print("Running Global Routing...")
            grt = ord.getGlobalRouter()

            # Find routing layers
            m1 = tech.findLayer("metal1")
            m6 = tech.findLayer("metal6")

            if m1 and m6:
                # Layers for signal routing range (M1 to M6)
                signal_low_layer_lvl = m1.getRoutingLevel()
                signal_high_layer_lvl = m6.getRoutingLevel()

                # Layers for clock routing range (Prompt implies same range as signal)
                clock_low_layer_lvl = signal_low_layer_lvl
                clock_high_layer_lvl = signal_high_layer_lvl

                grt.setMinRoutingLayer(signal_low_layer_lvl)
                grt.setMaxRoutingLayer(signal_high_layer_lvl)
                grt.setMinLayerForClock(clock_low_layer_lvl)
                grt.setMaxLayerForClock(clock_high_layer_lvl)

                # Set global routing iterations as requested (10 times) using Tcl command
                design.evalTclString("set_global_routing_iterations 10")
                print("Set Global Routing iterations to 10.")

                # Configure other GRT parameters (defaults are often reasonable)
                grt.setAdjustment(0.5) # Congestion adjustment factor
                grt.setVerbose(True)

                # Run global routing (True means congestion driven)
                grt.globalRoute(True)
                print("Global Routing complete.")
                can_proceed_grt = True
            else:
                missing_route_layers = []
                if not m1: missing_route_layers.append("metal1")
                if not m6: missing_route_layers.append("metal6")
                print(f"Error: Global Routing skipped. Required layer(s) not found: {', '.join(missing_route_layers)}.")
                can_proceed_grt = False
        else: # if not can_proceed_post_cts_dp
            print("Global Routing skipped because post-CTS detailed placement was skipped.")
            can_proceed_grt = False


        #------------------------------------------------------------------------------
        # Detailed Routing
        #------------------------------------------------------------------------------
        # Only run detailed routing if global routing ran successfully
        if can_proceed_grt:
            print("Running Detailed Routing...")
            drter = design.getTritonRoute()
            params = drt.ParamStruct() # Detailed router parameters

            # Find routing layers by name
            m1 = tech.findLayer("metal1")
            m6 = tech.findLayer("metal6")

            if m1 and m6:
                # Set routing layer range for detailed routing parameters struct
                params.bottomRoutingLayer = m1.getName()
                params.topRoutingLayer = m6.getName()
                print(f"Detailed routing layers set from {m1.getName()} to {m6.getName()}.")
            else:
                 print("Error: Metal1 or Metal6 layer not found for detailed routing parameters. Skipping detailed routing.")
                 # Set layers to empty strings to signal an error state for parameters
                 params.bottomRoutingLayer = ""
                 params.topRoutingLayer = ""

            # Check if routing layers were found before proceeding with DRT setup
            if params.bottomRoutingLayer and params.topRoutingLayer:
                # Configure other detailed routing parameters
                params.enableViaGen = True # Enable via generation
                params.drouteEndIter = 1 # Number of detailed routing iterations
                params.verbose = 1 # Verbosity level
                params.cleanPatches = True # Clean up routing patches
                params.doPa = True # Perform pin access routing
                params.singleStepDR = False # Do not run in single-step mode
                params.minAccessPoints = 1 # Minimum pin access points
                # Optional: output files for debug/analysis
                params.outputMazeFile = ""
                params.outputDrcFile = ""
                params.outputCmapFile = ""
                params.outputGuideCoverageFile = ""
                params.dbProcessNode = "" # Process node specific parameters (if any)
                params.viaInPinBottomLayer = "" # Via-in-pin settings (if any)
                params.viaInPinTopLayer = ""
                params.orSeed = -1 # Router seed (-1 for random)
                params.orK = 0 # Other optimization parameter

                # Set the configured parameters to the router object
                drter.setParams(params)

                # Run detailed routing
                drter.main()
                print("Detailed Routing complete.")
                can_proceed_dr = True
            else:
                print("Detailed Routing skipped due to missing layer definitions.")
                can_proceed_dr = False
        else: # if not can_proceed_grt
            print("Detailed Routing skipped because Global Routing was skipped.")
            can_proceed_dr = False


        #------------------------------------------------------------------------------
        # Write Output Files
        #------------------------------------------------------------------------------
        # Only write output if detailed routing completed successfully
        if can_proceed_dr:
            print("Writing output files...")
            # Write the final DEF database
            design.writeDef("final.def")
            print("Wrote final.def")

            # Write the final Verilog netlist (with physical instance names/locations)
            design.evalTclString("write_verilog final.v")
            print("Wrote final.v")

            # Optional: Write SPEF for post-route timing analysis
            # design.evalTclString("write_spef final.spef")
            # print("Wrote final.spef")

        else:
            print("Output files not written due to previous errors in routing stages.")

else: # if not can_proceed at the beginning
     print("Script stopped early due to initial setup errors.")

print("Script execution finished.")