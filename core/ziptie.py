""" 
the Ziptie class 
"""
import numpy as np
import numba_tools as nb
import matplotlib.pyplot as plt    
import tools

class ZipTie(object):
    """ 
    An incremental unsupervised clustering algorithm

    Input channels are clustered together into mutually co-active sets.
    A helpful metaphor is bundling cables together with zip ties.
    Cables that carry related signals are commonly co-active, 
    and are grouped together. Cables that are co-active with existing
    bundles can be added to those bundles. A single cable may be ziptied
    into several different bundles. Co-activity is estimated 
    incrementally, that is, the algorithm updates the estimate after 
    each new set of signals is received. 

    Zipties are arranged hierarchically within the agent's drivetrain. 
    The agent begins with only one ziptie and creates subsequent
    zipties as previous ones mature. 

    When stacked within a gearbox, 
    zipties form a sparse deep neural network (DNN). 
    This DNN has the extremely desirable characteristic of
    l-0 sparsity--the number of non-zero weights are minimized.
    The vast majority of weights in this network are zero,
    and the rest are one.
    This makes sparse computation feasible and allows for 
    straightforward interpretation and visualization of the
    features at each level.  

    Attributes
    ----------
    activity_threshold : float
        Threshold below which input activity is teated as zero.
    agglomeration_energy : 2D array of floats
        The accumulated agglomeration energy for each bundle-cable pair.
    agglomeration_threshold
        Threshold above which agglomeration energy results in agglomeration.
    bundles_full : bool
        If True, all the bundles in the ``ZipTie`` are full and learning stops.
    bundle_activities : array of floats
        The current set of bundle activities.
    bundle_map_cols, bundle_map_rows : array of ints
        To represent the sparse 2D bundle map, a pair of row and col 
        arrays are used. Rows are bundle indices, and cols are 
        feature indices.  The bundle map shows which cables 
        are zipped together to form which bundles. 
    bundle_map_size : int
        The maximum number of non-zero entries in the bundle map.
    bundle_scale : array of floats
        The maximum value observed for each bundle. This scales the
        bundles' activities such that they use the whole range between 
        0 and 1.
    cable_activities : array of floats
        The current set of input actvities. 
    cable_max : array of floats
        The maximum of each cable's activity.
    level : int
        The position of this ``ZipTie`` in the hierarchy. 
    max_num_bundles : int
        The maximum number of bundle outputs allowed.
    max_num_cables : int
        The maximum number of cable inputs allowed.
    name : str
        The name associated with the ``ZipTie``.
    norm_time : float
        The time constant over which normalization takes place. 
        Estimates of ``cable_mean`` and ``cable_dev`` are updated
        using leaky integration with a time constant of ``norm_time``.
    nucleation_energy : 2D array of floats
        The accumualted nucleation energy associated with each cable-cable pair.
    nucleation_threshold : float
        Threshold above which nucleation energy results in nucleation.
    num_bundles : int
        The number of bundles that have been created so far.
    n_map_entries: int
        The total number of bundle map entries that have been created so far.
    size : int
        In this implementation, a characteristic of the ``ZipTie`` equal to
        ``max_num_cables`` and ``max_num_bundles``. 
    """

    def __init__(self, num_cables, name='anonymous', level=0):
        """ 
        Initialize each map, pre-allocating ``num_cables``.

        Parameters
        ----------
        level : int
            The position of this ``ZipTie`` in the hierarchy.
        num_cables : int
            The number of inputs to the ``ZipTie``.
        name : str
            The name assigned to the ``ZipTie``.
            Default is 'anonymous'.
        """
        self.name = name
        self.level = level
        self.max_num_cables = num_cables
        self.max_num_bundles = self.max_num_cables
        self.size = self.max_num_bundles
        self.num_bundles = 0
        # User-defined constants
        self.nucleation_threshold = 10. * 5 ** self.level
        self.agglomeration_threshold = .5 * self.nucleation_threshold
        self.activity_threshold = .1
        self.bundles_full = False        
        self.bundle_activities = np.zeros(self.max_num_bundles)
        self.cable_activities = np.zeros(self.max_num_cables)

        # Normalization constants
        self.cable_max = np.zeros(self.max_num_cables)
        self.norm_time = 1e3

        map_size = (self.max_num_bundles, self.max_num_cables)
        # To represent the sparse 2D bundle map, a pair of row and col 
        # arrays are used. Rows are bundle indices, and cols are 
        # feature indices.
        self.bundle_map_size = 8 
        self.bundle_map_rows = -np.ones(self.bundle_map_size).astype(int)
        self.bundle_map_cols = -np.ones(self.bundle_map_size).astype(int)
        self.n_map_entries = 0
        self.agglomeration_energy = np.zeros(map_size)
        self.nucleation_energy = np.zeros((self.max_num_cables, 
                                           self.max_num_cables))

    def step(self, new_cable_activities):
        """ 
        Update co-activity estimates and calculate bundle activity 
        
        This step combines the projection of cables activities
        to bundle activities together with using the cable activities 
        to incrementally train the ``ZipTie``.

        Parameters
        ----------
        new_cable_activities : array of floats
            The most recent set of cable activities.

        Returns
        -------
        self.bundle_activities : array of floats
            The current activities of the bundles.
        """
        self.cable_activities = self._normalize(new_cable_activities)
        self._featurize()
        self._learn()

        return self.bundle_activities

    def _normalize(self, cable_activities):
        """
        Normalize activities so that they are predictably distrbuted.
        
        Use a running estimate of the maximum of each cable activity.
        Scale it so that the max would fall at 1.

        Normalization has several benefits. 
        1. It makes for fewer constraints on worlds and sensors. 
           Any sensor can return any range of values. 
        2. Gradual changes in sensors and the world can be adapted to.
        3. It makes the bundle creation heuristic more robust and
           predictable. The approximate distribution of cable 
           activities is known and can be designed for.

        Parameters
        ----------
        cable_activities : array of floats
            The current activity levels of the cables. 

        Returns
        -------
        normalized_cable_activities : array of floats
            The normalized activity levels of the cables.
        """
        if cable_activities.size < self.max_num_cables:
            cable_activities = tools.pad(cable_activities, self.max_num_cables)

        self.cable_max += (cable_activities - self.cable_max) * 1e-4 
        i_lo = np.where(cable_activities > self.cable_max)
        self.cable_max[i_lo] += (cable_activities[i_lo] - 
                                 self.cable_max[i_lo]) * 1e-2
        cable_activities = cable_activities / (self.cable_max + tools.epsilon)
        cable_activities = np.maximum(0., cable_activities)
        cable_activities = np.minimum(1., cable_activities)
        
        # Sparsify the cable activities to speed up processing.
        cable_activities[np.where(cable_activities < 
                                  self.activity_threshold)] = 0.

        normalized_cable_activities = cable_activities.copy()
        return normalized_cable_activities

    def _featurize(self):
        """
        Calculate how much the cables' activities contribute to each bundle. 

        Find bundle activities by taking the minimum input value
        in the set of cables in the bundle.
        """
        self.bundle_activities = np.zeros(self.max_num_bundles)
        if self.n_map_entries > 0:
            nb.find_bundle_activities(
                    self.bundle_map_rows[:self.n_map_entries], 
                    self.bundle_map_cols[:self.n_map_entries], 
                    self.cable_activities, self.bundle_activities)
        # The residual ``cable_activities`` after calculating 
        # ``bundle_activities`` are the ``nonbundle_activities``.
        self.nonbundle_activities = self.cable_activities.copy()
        self.nonbundle_activities[np.where(self.nonbundle_activities < 
                                           self.activity_threshold)] = 0.

    def _learn(self):
        """
        Update energies and the ``bundle_map``.
        """
        # As appropriate update the energies and create new bundles.
        if not self.bundles_full:
            self._create_new_bundles()
            self._grow_bundles()
        return

    def _create_new_bundles(self):
        """ 
        If the right conditions have been reached, create a new bundle.
        """
        # Incrementally accumulate nucleation energy.
        nb.nucleation_energy_gather(self.nonbundle_activities,
                                    self.nucleation_energy)
   
        # Don't accumulate nucleation energy between a cable and itself
        ind = np.arange(self.cable_activities.size).astype(int)
        self.nucleation_energy[ind,ind] = 0.

        results = -np.ones(3)
        nb.max_dense(self.nucleation_energy, results)
        max_energy = results[0]
        cable_index_a = int(results[1])
        cable_index_b = int(results[2])

        # Add a new bundle if appropriate
        if max_energy > self.nucleation_threshold:
            self.bundle_map_rows[self.n_map_entries] = self.num_bundles
            self.bundle_map_cols[self.n_map_entries] = cable_index_a
            self.increment_n_map_entries()
            self.bundle_map_rows[self.n_map_entries] = self.num_bundles
            self.bundle_map_cols[self.n_map_entries] = cable_index_b
            self.increment_n_map_entries()
            self.num_bundles += 1

            print ' '.join(['    ', self.name, 
                           'bundle', str(self.num_bundles), 
                           'added with cables', str(cable_index_a), 
                           str(cable_index_b)]) 

            # Check whether the ``ZipTie``'s capacity has been reached.
            if self.num_bundles == self.max_num_bundles:
                self.bundles_full = True

            # Reset the accumulated nucleation and agglomeration energy
            # for the two cables involved.
            self.nucleation_energy[cable_index_a, :] = 0.
            self.nucleation_energy[cable_index_b, :] = 0.
            self.nucleation_energy[:, cable_index_a] = 0.
            self.nucleation_energy[:, cable_index_b] = 0.
            self.agglomeration_energy[:, cable_index_a] = 0.
            self.agglomeration_energy[:, cable_index_b] = 0.
        return 

    def increment_n_map_entries(self):
        """
        Add one to ``n_map`` entries and grow the bundle map as needed.
        """
        self.n_map_entries += 1
        if self.n_map_entries >= self.bundle_map_size:
            self.bundle_map_size *= 2
            self.bundle_map_rows = tools.pad(self.bundle_map_rows, 
                                             self.bundle_map_size, 
                                             val=-1, dtype='int')
            self.bundle_map_cols = tools.pad(self.bundle_map_cols, 
                                             self.bundle_map_size, 
                                             val=-1, dtype='int')
        
    def _grow_bundles(self):
        """ 
        Update an estimate of co-activity between all cables.
        """
        # Incrementally accumulate agglomeration energy.
        nb.agglomeration_energy_gather(self.bundle_activities, 
                                       self.nonbundle_activities,
                                       self.num_bundles,
                                       self.agglomeration_energy)

        # Don't accumulate agglomeration energy between cables already 
        # in the same bundle 
        val = 0.
        if self.n_map_entries > 0:
            nb.set_dense_val(self.agglomeration_energy, 
                             self.bundle_map_rows[:self.n_map_entries], 
                             self.bundle_map_cols[:self.n_map_entries], 
                             val)

        results = -np.ones(3)
        nb.max_dense(self.agglomeration_energy, results)
        max_energy = results[0]
        cable_index = int(results[2])
        bundle_index = int(results[1])

        # Add a new bundle if appropriate
        if max_energy > self.agglomeration_threshold:
            # Make a copy of the growing bundle.
            for i in range(self.n_map_entries):
                if self.bundle_map_rows[i] == bundle_index:
                    self.bundle_map_rows[self.n_map_entries] = self.num_bundles
                    self.bundle_map_cols[self.n_map_entries] = (
                            self.bundle_map_cols[i])
                    self.increment_n_map_entries()
            # Add in the new cable. 
            self.bundle_map_rows[self.n_map_entries] = self.num_bundles
            self.bundle_map_cols[self.n_map_entries] = cable_index
            self.increment_n_map_entries()
            self.num_bundles += 1

            print ' '.join(['    ', self.name, 
                           'bundle', str(self.num_bundles), 
                           'added: bundle', str(bundle_index),
                           'and cable', str(cable_index)]) 

            # Check whether the ``ZipTie``'s capacity has been reached.
            if self.num_bundles == self.max_num_bundles:
                self.bundles_full = True

            # Reset the accumulated nucleation and agglomeration energy
            # for the two cables involved.
            self.nucleation_energy[cable_index, :] = 0.
            self.nucleation_energy[cable_index, :] = 0.
            self.nucleation_energy[:, cable_index] = 0.
            self.nucleation_energy[:, cable_index] = 0.
            self.agglomeration_energy[:, cable_index] = 0.
            self.agglomeration_energy[:, cable_index] = 0.
            self.agglomeration_energy[bundle_index, :] = 0.
            self.agglomeration_energy[bundle_index, :] = 0.
        return
        
    def get_index_projection(self, bundle_index):
        """ 
        Project ``bundle_index`` down to its cable indices.

        Parameters
        ----------
        bundle_index : int
            The index of the bundle to project onto its constituent cables.

        Returns
        -------
        projection : array of floats
            An array of zeros and ones, representing all the cables that
            contribute to the bundle. The values ``projection``
            corresponding to all the cables that contribute are 1.
        """
        projection = np.zeros(self.max_num_cables)
        for i in range(self.n_map_entries):
            if self.bundle_map_rows[i] == bundle_index:
                projection[self.bundle_map_cols[i]] = 1.
        return projection
        
    def visualize(self):
        """
        Turn the state of the ``ZipTie`` into an image.
        """
        print ' '.join(['ziptie', str(self.level)])
        # First list the bundles andthe cables in each.
        i_bundles = self.bundle_map_rows[:self.n_map_entries]
        i_cables = self.bundle_map_cols[:self.n_map_entries]
        i_bundles_unique = np.unique(i_bundles)
        if i_bundles_unique is not None:
            for i_bundle in i_bundles_unique:
                b_cables = list(np.sort(i_cables[np.where(
                        i_bundles == i_bundle)[0]]))
                print ' '.join(['    bundle', str(i_bundle), 
                                'cables:', str(b_cables)])
        plot = False
        if plot: 
            if self.n_map_entries > 0:
                # Render the bundle map.
                bundle_map = np.zeros((self.max_num_cables, 
                                       self.max_num_bundles))
                nb.set_dense_val(bundle_map, 
                                 self.bundle_map_rows[:self.n_map_entries],
                                 self.bundle_map_cols[:self.n_map_entries], 1.)
                tools.visualize_array(bundle_map, 
                                      label=self.name + '_bundle_map')

                # Render the agglomeration energy.
                label = '_'.join([self.name, 'agg_energy'])
                tools.visualize_array(self.agglomeration_energy, label=label)
                plt.xlabel( str(np.max(self.agglomeration_energy)) )

                # Render the nucleation energy.
                label = '_'.join([self.name, 'nuc_energy'])
                tools.visualize_array(self.nucleation_energy, label=label)
                plt.xlabel( str(np.max(self.nucleation_energy)) )
