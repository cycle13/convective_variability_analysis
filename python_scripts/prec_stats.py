"""
Filename:     prec_hist.py
Author:       Stephan Rasp, s.rasp@lmu.de
Description:  Compute and plot precipitation histograms of deterministic and 
              ensemble runs and observations

"""

# Import modules
import argparse
from netCDF4 import Dataset
from datetime import datetime, timedelta
from helpers import make_datelist, get_radar_mask, get_pp_fn, \
    get_datalist_radar, create_log_str, get_datalist_model, \
    read_netcdf_dataset, get_config, save_fig_and_log, pp_exists, \
    get_composite_str, calc_rdf, identify_clouds
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import convolve2d
from scipy.stats import binned_statistic


################################################################################
# PREPROCESSING FUNCTIONS
################################################################################
def create_bin_edges(inargs):
    """
    Create the bin edges from input parameters

    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments

    Returns
    -------
    prec_freq_binedges, cld_size_binedges, cld_prec_binedges,
    cld_size_sep_binedges, cld_prec_sep_binedges : numpy.arrays
      Bin edges
    """

    prec_freq_binedges = inargs.cld_freq_binedges
    cld_size_binedges = np.linspace(inargs.cld_size_bin_triplet[0],
                                    inargs.cld_size_bin_triplet[1],
                                    inargs.cld_size_bin_triplet[2])
    cld_prec_binedges = np.linspace(inargs.cld_prec_bin_triplet[0],
                                    inargs.cld_prec_bin_triplet[1],
                                    inargs.cld_prec_bin_triplet[2])
    cld_size_sep_binedges = np.linspace(inargs.cld_size_sep_bin_triplet[0],
                                        inargs.cld_size_sep_bin_triplet[1],
                                        inargs.cld_size_sep_bin_triplet[2])
    cld_prec_sep_binedges = np.linspace(inargs.cld_prec_sep_bin_triplet[0],
                                        inargs.cld_prec_sep_bin_triplet[1],
                                        inargs.cld_prec_sep_bin_triplet[2])
    return prec_freq_binedges, cld_size_binedges, cld_prec_binedges, \
           cld_size_sep_binedges, cld_prec_sep_binedges


def create_netcdf(inargs):
    """
    Creates a NetCDF object to store data.

    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments

    Returns
    -------
    rootgroup : NetCDF object

    """

    prec_freq_binedges, cld_size_binedges, cld_prec_binedges, \
        cld_size_sep_binedges, cld_prec_sep_binedges = create_bin_edges(inargs)

    datearray = np.array(make_datelist(inargs, out_format='netcdf'))
    timearray = np.arange(inargs.time_start, inargs.time_end + inargs.time_inc,
                          inargs.time_inc)
    rdf_radius = np.arange(0., inargs.rdf_r_max + inargs.rdf_dr, inargs.rdf_dr)
    rdf_radius = (rdf_radius[:-1] + rdf_radius[1:]) / 2.
    groups = ['obs', 'det', 'ens']
    dimensions = {
        'time': timearray,
        'date': datearray,
        'prec_freq_bins': np.array(prec_freq_binedges[1:]),
        'cld_size_bins': np.array(cld_size_binedges[1:]),
        'cld_prec_bins': np.array(cld_prec_binedges[1:]),
        'cld_size_sep_bins': np.array(cld_size_sep_binedges[1:]),
        'cld_prec_sep_bins': np.array(cld_prec_sep_binedges[1:]),
        'rdf_radius': rdf_radius
    }
    variables = {
        'prec_freq': ['date', 'time', 'prec_freq_bins'],
        'cld_size': ['date', 'time', 'cld_size_bins'],
        'cld_prec': ['date', 'time', 'cld_prec_bins'],
        'cld_size_sep': ['date', 'time', 'cld_size_sep_bins'],
        'cld_prec_sep': ['date', 'time', 'cld_size_sep_bins'],
        'cld_size_mean': ['date', 'time'],
        'cld_prec_mean': ['date', 'time'],
        'cld_size_sep_mean': ['date', 'time'],
        'cld_prec_sep_mean': ['date', 'time'],
        'rdf': ['date', 'time', 'rdf_radius'],
        'rdf_sep': ['date', 'time', 'rdf_radius'],
    }

    pp_fn = get_pp_fn(inargs)

    # Create NetCDF file
    rootgroup = Dataset(pp_fn, 'w', format='NETCDF4')
    rootgroup.log = create_log_str(inargs, 'Preprocessing')

    # Create root dimensions and variables
    for dim_name, dim_val in dimensions.items():
        rootgroup.createDimension(dim_name, dim_val.shape[0])
        tmp_var = rootgroup.createVariable(dim_name, 'f8', dim_name)
        tmp_var[:] = dim_val

    # Create group dimensions and variables
    [b.append('ens_no') for a, b in variables.items()]
    dimensions['ens_no'] = 1

    for g in groups:
        rootgroup.createGroup(g)
        if g == 'ens':
            dimensions['ens_no'] = inargs.nens

        # Create dimensions
        for dim_name, dim_len in dimensions.items():
            if type(dim_len) is not int:
                dim_len = dim_len.shape[0]
            rootgroup.groups[g].createDimension(dim_name, dim_len)

        # Create variables
        for var_name, var_dims in variables.items():
            rootgroup.groups[g].createVariable(var_name, 'f8', var_dims)

    return rootgroup


def compute_cloud_histograms(inargs, data, rootgroup, group, idate, it, ie,
                             cld_size_binedges, cld_prec_binedges,
                             cld_size_sep_binedges, cld_prec_sep_binedges):
    """
    Compute the histograms for the given parameters and wirte in netCDF file
    
    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments
    data : numpy array
      2D precipitation array
    rootgroup : ncdf rootgroup
      rootgroup to write 
    group : str
      NetCDF group name
    idate : int
      Date index
    it : int 
      time index
    ie : int
      Ensemble index
    cld_size_binedges : numpy array or list
      Bin edges
    cld_prec_binedges : numpy array or list
      Bin edges
    cld_size_sep_binedges : numpy array or list
      Bin edges
    cld_prec_sep_binedges : numpy array or list
      Bin edges

    Returns
    -------
    labels, labels_sep : numpy.array
      2D array with labelled objects, for regular and separated clouds
      
    """
    dx = float(get_config(inargs, 'domain', 'dx'))
    data[data.mask] = 0  # set all masked points to zero, otherwise strage...

    labels, cld_size_list, cld_prec_list = \
        identify_clouds(data, inargs.thresh, water=False,
                        dx=dx)

    # Convert to kg / h
    cld_prec_list = np.array(cld_prec_list) * dx * dx
    rootgroup.groups[group].variables['cld_size']\
        [idate, it, :, ie] = np.histogram(cld_size_list,
                                          cld_size_binedges)[0]
    rootgroup.groups[group].variables['cld_prec']\
        [idate, it, :, ie] = np.histogram(cld_prec_list,
                                          cld_prec_binedges)[0]
    rootgroup.groups[group].variables['cld_size_mean']\
        [idate, it, ie] = np.mean(cld_size_list)
    rootgroup.groups[group].variables['cld_prec_mean']\
        [idate, it, ie] = np.mean(cld_prec_list)

    if inargs.sep_perimeter == 0:   # Use default cross
        footprint = [[0,1,0],[1,1,1],[0,1,0]]
    else:
        footprint = inargs.sep_perimeter
    labels_sep, cld_size_sep_list, cld_prec_sep_list = \
        identify_clouds(data, inargs.thresh, water=True,
                        dx=dx, neighborhood=footprint)

    # Convert to kg / h
    cld_prec_sep_list = np.array(cld_prec_sep_list) * dx * dx
    rootgroup.groups[group].variables['cld_size_sep']\
        [idate, it, :, ie] = \
        np.histogram(cld_size_sep_list,
                     cld_size_sep_binedges)[0]
    rootgroup.groups[group].variables['cld_prec_sep']\
        [idate, it, :, ie] = \
        np.histogram(cld_prec_sep_list,
                     cld_prec_sep_binedges)[0]
    rootgroup.groups[group].variables['cld_size_sep_mean']\
        [idate, it, ie] = np.mean(cld_size_sep_list)
    rootgroup.groups[group].variables['cld_prec_sep_mean']\
        [idate, it, ie] = np.mean(cld_prec_sep_list)

    return labels, labels_sep


def compute_rdfs(inargs, labels, labels_sep, data, rdf_mask, rootgroup, group,
                 idate, it, ie):
    """
    Compute RDF. Type given by input parameters
    
    Parameters
    ----------
    inargs
    labels
    labels_sep
    data
    rdf_mask
    rootgroup
    group
    idate
    it
    ie

    """

    # Compute mask for rdfs
    r_max = inargs.rdf_r_max
    kernel_size = r_max * 2 + 1
    y_tmp, x_tmp = np.ogrid[-r_max:kernel_size - r_max,
                   -r_max:kernel_size - r_max]
    kernel = x_tmp * x_tmp + y_tmp * y_tmp <= r_max * r_max
    rdf_mask = convolve2d(rdf_mask, kernel, mode='same', boundary='fill',
                          fillvalue=1) == 0

    if inargs.rdf_sep:
        tmp_labels = labels_sep
    else:
        tmp_labels = labels

    for l, rdf_type in zip([labels, labels_sep], ['rdf', 'rdf_sep']):

        if np.sum(l > 0)/np.float(l.size) > inargs.rdf_cov_thresh:
            rdf, radius = calc_rdf(l, data,
                                   normalize=~inargs.rdf_non_norm,
                                   dx=float(get_config(inargs, 'domain', 'dx')),
                                   r_max=inargs.rdf_r_max,
                                   dr=inargs.rdf_dr,
                                   mask=rdf_mask)
        else:
            rdf = np.nan

        rootgroup.groups[group].variables[rdf_type][idate, it, :, ie] \
            = rdf

    # End function


def prec_stats(inargs):
    """
    Compute and save precipitation amount and cloud size and cloud 
    precipitation histograms and radial distrubution function.
    
    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments


    """

    # TODO: This function is also called in create_ncdf, could do better!
    prec_freq_binedges, cld_size_binedges, cld_prec_binedges, \
        cld_size_sep_binedges, cld_prec_sep_binedges = create_bin_edges(inargs)

    # Make netCDF file
    rootgroup = create_netcdf(inargs)

    # TODO: This is somewhat the same as domain_mean_weather_ts
    radar_mask = get_radar_mask(inargs)

    # Load analysis data and store in NetCDF
    for idate, date in enumerate(make_datelist(inargs)):
        print('Computing prec_hist for: ' + date)

        # Determine radar mask
        if inargs.radar_mask == 'total':
            tmp_mask = np.any(radar_mask, axis=(0, 1))
        elif inargs.radar_mask == 'day':
            tmp_mask = np.any(radar_mask[idate], axis=0)
        elif inargs.radar_mask == 'hour':
            tmp_mask = radar_mask[idate]

        for group in rootgroup.groups:
            for ie in range(rootgroup.groups[group].dimensions['ens_no'].size):
                if group in ['det', 'ens']:
                    if group == 'det':
                        ens_no = 'det'
                    else:
                        ens_no = ie + 1
                    datalist = get_datalist_model(inargs, date, ens_no,
                                                  'PREC_ACCUM', tmp_mask)
                elif group == 'obs':
                    datalist = get_datalist_radar(inargs, date, tmp_mask)
                else:
                    raise Exception('Wrong group.')

                # Now do the actually new calculation
                for it, data in enumerate(datalist):
                    # Data is the precipitation field for one hour

                    # 1st: calculate totla precipitation histogram
                    rootgroup.groups[group].variables['prec_freq']\
                        [idate, it, :, ie] = np.histogram(data,
                                                          prec_freq_binedges)[0]

                    # 2nd: compute cloud size and precipitation histograms
                    tmp = compute_cloud_histograms(inargs, data, rootgroup,
                                                   group, idate, it, ie,
                                                   cld_size_binedges,
                                                   cld_prec_binedges,
                                                   cld_size_sep_binedges,
                                                   cld_prec_sep_binedges)
                    labels, labels_sep = tmp

                    # 3rd: Compute radial distribution function
                    if tmp_mask.ndim == 3:
                        rdf_mask = tmp_mask[it]
                    elif tmp_mask.ndim == 2:
                        rdf_mask = tmp_mask
                    else:
                        raise Exception('Wrong dimensions for radar mask')

                    compute_rdfs(inargs, labels, labels_sep, data, rdf_mask,
                                 rootgroup, group, idate, it, ie)

    # Close NetCDF file
    rootgroup.close()


################################################################################
# PLOTTING FUNCTIONS
################################################################################
def plot_prec_freq_hist(inargs):
    """
    Plot precipitation histogram comparing the three groups
    
    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments

    """

    # Read pre-processed data
    rootgroup = read_netcdf_dataset(inargs)

    # Set up figure
    fig, ax = plt.subplots(1, 1, figsize=(4, 3.5))
    x = np.arange(rootgroup.variables['prec_freq_bins'][:].shape[0])

    # Loop over groups
    for ig, group in enumerate(rootgroup.groups):
        # Compute mean in all directions but bins
        mean_hist = np.mean(rootgroup.groups[group].variables['prec_freq'][:],
                            axis=(0, 1, 3))
        ax.bar(x[1:] + ig * 0.2, mean_hist[1:], width=0.2,
               color=get_config(inargs, 'colors', group), label=group)

    # Make figure look nice
    ax.legend(loc=0, prop={'size': 10})
    plt.xticks(x[1:], rootgroup.variables['prec_freq_bins'][:-1])
    ax.set_xlabel('Hourly accumulation [mm/h]')
    ax.set_ylabel('Number of grid points')
    date_str = get_composite_str(inargs, rootgroup)
    ax.set_title(date_str, fontsize=12)

    plt.tight_layout()

    # Save figure and log
    save_fig_and_log(fig, rootgroup, inargs, 'prec_freq_hist')


def plot_cloud_size_prec_hist(inargs):
    """
    Plot histograms of cloud size and precipitation
    
    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments

    """

    # Read pre-processed data
    rootgroup = read_netcdf_dataset(inargs)

    # Set up figure
    fig, axmat = plt.subplots(2, 4, figsize=(10, 7), sharey=True)

    # Convert data for plotting
    for isep, sep in enumerate(['_sep', '']):
        for ityp, typ in enumerate(['cld_size', 'cld_prec']):
            right_edges = rootgroup.variables[typ + sep + '_bins'][:]
            x = right_edges - np.diff(right_edges)[0] / 2

            if ityp == 0:
                xlabel = 'Cloud size [m^2]'
            else:
                xlabel = 'Cloud precipitation [kg /h]'

            # Loop over groups
            for ig, group in enumerate(rootgroup.groups):
                # Load data
                hist_data = rootgroup.groups[group].variables[typ + sep][:]

                if inargs.cld_y_type == 'relative_frequency':
                    mean_hist = np.mean(hist_data, axis=(0, 1, 3))

                    # Convert to relative frequency
                    mean_hr_no_cld = np.sum(mean_hist)  # Mean hourly cloud sum
                    plot_data = mean_hist / mean_hr_no_cld
                elif inargs.cld_y_type == 'mean_number':
                    plot_data = np.mean(hist_data, axis=(0, 1, 3))
                elif inargs.cld_y_type == 'total_number':
                    plot_data = np.mean(hist_data, axis=3)
                    plot_data = np.sum(plot_data, axis=(0, 1))
                else:
                    raise Exception('cld_y_type wrong!')

                # Plot on log-linear
                ax = axmat[isep, ityp * 2]
                ax.plot(x, plot_data, color=get_config(inargs, 'colors', group),
                        label=group)
                ax.set_yscale('log')
                ax.set_title(typ + sep)
                ax.set_xlabel(xlabel)

                # plot on log-log
                ax = axmat[isep, ityp * 2 + 1]
                ax.plot(x, plot_data, color=get_config(inargs, 'colors', group),
                        label=group)
                ax.set_yscale('log')
                ax.set_xscale('log')
                ax.set_title(typ + sep)
                ax.set_xlabel(xlabel)

                if inargs.cld_y_type == 'relative_frequency':
                    ax.set_ylim(5e-5, 1e0)

    axmat[0, 0].set_ylabel(inargs.cld_y_type)
    axmat[1, 0].set_ylabel(inargs.cld_y_type)
    axmat[0, 0].legend(loc=0)
    fig.suptitle('Composite ' + get_composite_str(inargs, rootgroup))
    plt.tight_layout(rect=[0, 0, 1, 0.93])

    # Save figure and log
    save_fig_and_log(fig, rootgroup, inargs, 'cld_size_prec_hist')


def plot_rdf_individual(inargs):
    """
    Plots the radial distribution function as panel over all days. This copies some stuff from 
    plot_domain_mean_timeseries_individual in weather_time_series.py
    
    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments

    """

    # Read pre-processed data
    rootgroup = read_netcdf_dataset(inargs)
    n_days = rootgroup.dimensions['date'].size

    # Set up figure
    n_cols = 4
    n_rows = int(np.ceil(float(n_days) / n_cols))

    fig, axmat = plt.subplots(n_rows, n_cols, sharex=True, sharey=True,
                              figsize=(10, 3 * n_rows))
    axflat = np.ravel(axmat)

    # Loop over axes / days
    for iday in range(n_days):
        dateobj = (timedelta(seconds=int(rootgroup.variables['date'][iday])) +
                   datetime(1, 1, 1))
        datestr = dateobj.strftime(get_config(inargs, 'plotting', 'date_fmt'))
        axflat[iday].set_title(datestr)
        if iday >= ((n_cols * n_rows) - n_cols):  # Only bottom row
            axflat[iday].set_xlabel('Time [UTC]')

        for ig, group in enumerate(rootgroup.groups):

            # Get data
            if inargs.rdf_sep:
                rdf_data = rootgroup.groups[group].variables['rdf_sep'][iday]
            else:
                rdf_data = rootgroup.groups[group].variables['rdf'][iday]
            # Convert data which at this point has dimensions
            # [time, radius, ens mem]

            # Mean over ensemble dimension
            rdf = np.nanmax(np.nanmean(rdf_data, axis=2), axis=1)

            # Plot data
            axflat[iday].plot(rootgroup.variables['time'][:], rdf, label=group,
                              c=get_config(inargs, 'colors', group))

            axflat[iday].set_ylim(0, 35)

    # Finish figure
    axflat[0].legend(loc=0)

    plt.tight_layout()

    # Save figure and log
    save_fig_and_log(fig, rootgroup, inargs, 'rdf_individual')


def plot_rdf_composite(inargs):
    """
    Plots the radial distribution function as panel over all days. This copies 
    some stuff from plot_domain_mean_timeseries_composite in 
    weather_time_series.py

    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments

    """

    # Read pre-processed data
    rootgroup = read_netcdf_dataset(inargs)
    fig, axarr = plt.subplots(1, 2, figsize=(6, 3))

    axarr[0].set_ylabel('RDF')
    for group in rootgroup.groups:
        if inargs.no_det and group == 'det':
            continue
        if inargs.rdf_sep:
            array = rootgroup.groups[group].variables['rdf_sep'][:]
        else:
            array = rootgroup.groups[group].variables['rdf'][:]
        # Convert data which at this point has dimensions
        # [date, time, radius, ens mem]

        # 1st: Plot max curve
        mx = np.nanmax(np.nanmean(array, axis=(0, 3)), axis=1)
        axarr[0].plot(rootgroup.variables['time'][:], mx, label=group,
                 c=get_config(inargs, 'colors', group))

        # 2nd: Plot example curves
        for t in inargs.rdf_curve_times:
            rdf_curve = np.nanmean(array[:, t, :, :], axis=(0, 2))
            axarr[1].plot(rootgroup.variables['rdf_radius'][:] * 2.8, rdf_curve,
                          label=group + ' ' + str(rootgroup.variables['time'][t]))

    axarr[0].set_ylim(0, 15)
    axarr[0].set_xlabel('Time [UTC]')
    axarr[1].set_xlabel('Radius [km]')

    axarr[0].set_title('RDF maximum')
    axarr[1].set_title('RDF curves')

    axarr[0].legend(loc=0)
    axarr[1].legend(loc=0)

    fig.suptitle('Composite ' + get_composite_str(inargs, rootgroup) +
                 ' sep = ' + str(inargs.rdf_sep) +
                 ' perimeter = ' + str(inargs.sep_perimeter))
    plt.tight_layout(rect=[0, 0, 1, 0.93])

    # Save figure and log
    save_fig_and_log(fig, rootgroup, inargs, 'rdf_composite')


################################################################################
# MAIN FUNCTION
################################################################################
def main(inargs):
    """
    Runs the main program

    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments
    """

    # Check if pre-processed file exists
    if (pp_exists(inargs) is False) or (inargs.recompute is True):
        print('Compute preprocessed file: ' + get_pp_fn(inargs))
        # Call preprocessing routine with arguments
        prec_stats(inargs)
    else:
        print('Found pre-processed file:' + get_pp_fn(inargs))

    # Plotting
    if 'prec_freq_hist' in inargs.which_plot:
        plot_prec_freq_hist(inargs)
    if 'prec_size_hist' in inargs.which_plot:
        plot_cloud_size_prec_hist(inargs)
    if 'rdf' in inargs.which_plot:
        plot_rdf_individual(inargs)
        plot_rdf_composite(inargs)


if __name__ == '__main__':

    description = __doc__

    parser = argparse.ArgumentParser(description=description)

    parser.add_argument('--date_start',
                        type=str,
                        help='Start date of analysis in yyyymmddhh')
    parser.add_argument('--date_end',
                        type=str,
                        help='End date of analysis in yyyymmddhh')
    parser.add_argument('--time_start',
                        type=int,
                        default=1,
                        help='Analysis start time in hrs [including]. \
                              Default = 1')
    parser.add_argument('--time_end',
                        type=int,
                        default=24,
                        help='Analysis end time in hrs [including]. \
                              Default = 24')
    parser.add_argument('--time_inc',
                        type=float,
                        default=1,
                        help='Analysis increment in hrs. Default = 1')
    parser.add_argument('--nens',
                        type=int,
                        help='Number of ensemble members')
    parser.add_argument('--cld_y_type',
                        type=str,
                        default='relative_frequency',
                        help='Which y-axis scale for cloud plot. '
                             '[relative_frequency, mean_number, total_number]')
    parser.add_argument('--radar_mask',
                        type=str,
                        default='hour',
                        help='Radar mask for [hour, day, total]?')
    parser.add_argument('--sep_perimeter',
                        type=int,
                        default=5,
                        help='Size of search matrix for cloud separation')
    parser.add_argument('--thresh',
                        type=float,
                        default=1.,
                        help='Threshold for cloud object identification.')

    parser.add_argument('--cld_freq_binedges',
                        nargs='+',
                        type=float,
                        default=[0, 0.1, 0.2, 0.5, 1, 2, 5, 10, 1000],
                        help='List of binedges.')
    parser.add_argument('--cld_size_bin_triplet',
                        nargs='+',
                        type=float,
                        default=[0, 1.6464e9, 60],
                        help='Triplet for binedge creation. '
                             '[start_left, end_right, n_bins]')
    parser.add_argument('--cld_prec_bin_triplet',
                        nargs='+',
                        type=float,
                        default=[0, 3.5e9, 60],
                        help='Triplet for binedge creation. '
                             '[start_left, end_right, n_bins]')
    parser.add_argument('--cld_size_sep_bin_triplet',
                        nargs='+',
                        type=float,
                        default=[0, 4.704e8, 60],
                        help='Triplet for binedge creation. '
                             '[start_left, end_right, n_bins]')
    parser.add_argument('--cld_prec_sep_bin_triplet',
                        nargs='+',
                        type=float,
                        default=[0, 1e9, 60],
                        help='Triplet for binedge creation. '
                             '[start_left, end_right, n_bins]')

    parser.add_argument('--rdf_r_max',
                        type=float,
                        default=30,
                        help='Maximum serach radius in grid points for RDF.')
    parser.add_argument('--rdf_dr',
                        type=float,
                        default=1,
                        help='Radial bin size for RDF in grid points.')
    parser.add_argument('--rdf_sep',
                        dest='rdf_sep',
                        action='store_true',
                        help='If given, compute RDF for separated clouds.')
    parser.set_defaults(rdf_sep=False)
    parser.add_argument('--rdf_non_norm',
                        dest='rdf_non_norm',
                        action='store_true',
                        help='If given, compute the non-normalized RDF.')
    parser.set_defaults(rdf_non_norm=False)
    parser.add_argument('--rdf_cov_thresh',
                        type=float,
                        default=0,
                        help='Minimum coverage fraction for RDF calculation.')
    parser.add_argument('--rdf_curve_times',
                        type=int,
                        nargs='+',
                        default=[15, 21],
                        help='Times [UTC} for which to display RDF curves')

    parser.add_argument('--no_det',
                        dest='no_det',
                        action='store_true',
                        help='If given, Do not show det in plots.')
    parser.set_defaults(no_det=False)
    parser.add_argument('--which_plot',
                        type=str,
                        nargs='+',
                        default=['prec_freq_hist', 'prec_size_hist', 'rdf'],
                        help='If nothing listed, plots all of \
                                 [prec_freq_hist, prec_size_hist, rdf]')

    parser.add_argument('--config_file',
                        type=str,
                        default='config.yml',
                        help='Config file in relative directory ../config. \
                              Default = config.yml')
    parser.add_argument('--sub_dir',
                        type=str,
                        default='prec_stats',
                        help='Sub-directory for figures and pp_files')
    parser.add_argument('--plot_name',
                        type=str,
                        default='',
                        help='Custom plot name.')
    parser.add_argument('--pp_name',
                        type=str,
                        default='',
                        help='Custom name for preprocessed file.')
    parser.add_argument('--recompute',
                        dest='recompute',
                        action='store_true',
                        help='If given, recompute pre-processed file.')
    parser.set_defaults(recompute=False)

    args = parser.parse_args()

    main(args)